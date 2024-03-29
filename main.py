import tensorflow as tf
import simulation_params
import security_technicals
import stock_lstm
import build_input
import evaluate_predictions
import time
import numpy as np
from datetime import datetime, timedelta

def main(_):
    beginDate = '2009-04-25'
    endDate = '2015-02-27'
    params = simulation_params.SimulationParams(startDate=beginDate, endDate=endDate,
                                                securityTicker='GILD',
                                                movingAveragePeriods=[20, 50, 100],
                                                batchSize=64,
                                                hiddenSize=256,
                                                numLayers=3,
                                                keepProb=0.8,
                                                maxGradNorm=1,
                                                numEpochs=100,
                                                lrDecay=0.95,
                                                learningRate=0.08,
                                                initScale=0.5,
                                                priceChangeScale=100,
                                                numPredictionDays=300)

    technicals = security_technicals.Technicals(params)
    technicals.loadDataInMemory()

    def run_epoch(session, m, inputTechnicals, inputParams, eval_op, verbose=False, lastState=None):
        dataLen = len(inputTechnicals.getUsefulClosePrices()) * inputParams.technicalsPerPrice
        batch_len = ((dataLen // m.batch_size) - 1)
        epoch_size = batch_len // m.num_steps
        print 'epoch_size = ' + str(epoch_size)
        start_time = time.time()
        costs = 0.0
        iters = 0
        state = lastState
        concatenatedResults = None
        for step, (x, y) in enumerate(build_input.get_iterators(inputTechnicals, inputParams)):
            capturedParams = {m.input_data: x, m.targets: y}
            if state is not None:
                capturedParams[m.initial_state] = state

            cost, state, targets, output, sparse_soft_max, _ = session.run([m.cost, m.final_state, m.targets, m.output, m._sparse_softmax_cross_entropy, eval_op], capturedParams)
            costs += cost
            iters += m.num_steps

            if concatenatedResults is None:
                concatenatedResults = output
            else:
                concatenatedResults = np.concatenate((concatenatedResults, output))

            if verbose:
                #print 'cross entropy: ' + str(sparse_soft_max)
                print 'output: ' + str(output)
                print 'target: ' + str(targets)

            print_interval = 20
            if verbose and epoch_size > print_interval \
                    and step % (epoch_size // print_interval) == print_interval:
                print("%.3f mse: %.8f speed: %.0f ips" % (step * 1.0 / epoch_size, costs / iters,
                     iters * m.batch_size / (time.time() - start_time)))

        return costs / (iters if iters > 0 else 1), state, concatenatedResults


    with tf.Graph().as_default(), tf.Session() as session:
        initializer = tf.random_uniform_initializer(-params.initScale, params.initScale)
        with tf.variable_scope("model", reuse=None, initializer=initializer):
            m = stock_lstm.StockLSTM(is_training=True, simulationParams=params)

        tf.global_variables_initializer().run()

        cachedStateBetweenEpochs = None
        for epoch in xrange(params.numEpochs):
            lr_decay = params.lrDecay ** epoch
            print 'lr_decay = ' + str(lr_decay)
            m.assign_lr(session, params.learningRate * lr_decay)
            cur_lr = session.run(m.lr)

            mse, cachedStateBetweenEpochs, _ = run_epoch(session, m, technicals, params, m.train_op, verbose=False, lastState=cachedStateBetweenEpochs)
            m.is_training = False
            vmse, _, _ = run_epoch(session, m, technicals, params, tf.no_op(), lastState=cachedStateBetweenEpochs)
            m.is_training = True
            print("Epoch: %d - learning rate: %.3f - train mse: %.3f - test mse: %.3f" %
                  (epoch, cur_lr, mse, vmse))

        params.startDate = params.endDate
        endDatetime = datetime.strptime(params.startDate, "%Y-%m-%d")
        endDatetime += timedelta(days=params.numPredictionDays)
        params.endDate = endDatetime.strftime("%Y-%m-%d")

        technicals = security_technicals.Technicals(params)
        technicals.loadDataInMemory()
        m.is_training = False
        tmse, _, outputs = run_epoch(session, m, technicals, params, tf.no_op(), verbose=True, lastState=cachedStateBetweenEpochs)
        print("Test mse: %.3f" % tmse)

        initialValue = 1000
        finalValue = evaluate_predictions.fetch_final_value(initialValue, outputs, technicals.getUsefulClosePrices(), 5.0)
        print 'Final value of %f initial is %f' % (initialValue, finalValue)

        usefulPrices = technicals.getUsefulClosePrices()
        naiveFinalValue = (usefulPrices[-1] / usefulPrices[0]) * initialValue
        print 'Naive final value is %f' % (naiveFinalValue)

    return 0

if __name__ == "__main__":
    tf.app.run()