import numpy as np
import os, sys
from os.path import join
import matplotlib.pyplot as plt
import neo
import elephant
import scipy.signal as ss
import scipy.stats as stats
import scipy.io as sio
from scipy.optimize import linear_sum_assignment
import quantities as pq
import json
import yaml
import time
import h5py
import ipdb
import mne

from tools import *
from neuroplot import *
import MEAutility as MEA
from spike_sorting import plot_mixing, plot_templates, templates_weights
import ICA as ica
import orICA as orica

root_folder = os.getcwd()
plt.ion()
plt.show()

def matcorr(x, y, rmmean=False, weighting=None):
    m, n = x.shape
    p, q = y.shape
    m = np.min([m,p])

    if m != n or  p!=q:
        print 'matcorr(): Matrices are not square: using max abs corr method (2).'
        method = 2

    if n != q:
      raise Exception('Rows in the two input matrices must be the same length.')

    if rmmean:
      x = x - np.mean(x, axis=1) # optionally remove means
      y = y - np.mean(y, axis=1)

    dx = np.sum(x**2, axis=1)
    dy = np.sum(y**2, axis=1)
    dx[np.where(dx==0)] = 1
    dy[np.where(dy==0)] = 1
    # raise Exception()
    corrs = np.matmul(x, y.T)/np.sqrt(dx[:, np.newaxis]*dy[np.newaxis, :])

    if weighting != None:
        if any(corrs.shape != weighting.shape):
            print 'matcorr(): weighting matrix size must match that of corrs'
        else:
            corrs = corrs * weighting

    cc = np.abs(corrs)

    # Performs Hungarian algorithm matching
    col_ind, row_ind = linear_sum_assignment(-cc.T)

    idx = np.argsort(-cc[row_ind, col_ind])
    corr = corrs[row_ind, col_ind][idx]
    indy = np.arange(m)[idx]
    indx = row_ind[idx]

    return corr, indx, indy, corrs

def plot_topo_eeg(a, pos):
    '''

    Parameters
    ----------
    a
    pos

    Returns
    -------

    '''
    from mne.viz import plot_topomap

    n_sources = len(a)
    cols = int(np.ceil(np.sqrt(n_sources)))
    rows = int(np.ceil(n_sources / float(cols)))
    fig_t = plt.figure()

    for n in range(n_sources):
        ax_w = fig_t.add_subplot(rows, cols, n + 1)
        mix = mixing[n] / np.ptp(mixing[n])
        plot_topomap(a[n], pos, axes=ax_w)

    return fig_t

if __name__ == '__main__':
    if '-r' in sys.argv:
        pos = sys.argv.index('-r')
        folder = sys.argv[pos + 1]
    if '-mod' in sys.argv:
        pos = sys.argv.index('-mod')
        mod = sys.argv[pos + 1]
    else:
        mod = 'orica'
    if '-block' in sys.argv:
        pos = sys.argv.index('-block')
        block_size = int(sys.argv[pos + 1])
    else:
        block_size = 500
    if '-ff' in sys.argv:
        pos = sys.argv.index('-ff')
        ff = sys.argv[pos + 1]
    else:
        ff = 'constant'
    if '-mu' in sys.argv:
        pos = sys.argv.index('-mu')
        mu = float(sys.argv[pos + 1])
    else:
        mu = 0
    if '-lambda' in sys.argv:
        pos = sys.argv.index('-lambda')
        lambda_val = float(sys.argv[pos + 1])
    else:
        lambda_val = 0.995
    if '-oricamod' in sys.argv:
        pos = sys.argv.index('-oricamod')
        oricamod = sys.argv[pos + 1]
    else:
        oricamod = 'original'
    if '-npass' in sys.argv:
        pos = sys.argv.index('-npass')
        npass = int(sys.argv[pos + 1])
    else:
        npass = 1
    if '-reg' in sys.argv:
        pos = sys.argv.index('-reg')
        reg = int(sys.argv[pos + 1])
    else:
        reg = 'L2'
    if '-noplot' in sys.argv:
        plot_fig = False
    else:
        plot_fig = True

    if len(sys.argv) == 1:
        print 'Evaluate ICA for spike sorting:\n   -r recording folder\n   -mod orica-ica\n   \nblock block size' \
              '\n   -ff constant-cooling\n   -mu smoothing\n   -lambda lambda_0' \
              '\n   -oricamod  original - A - W - A_block - W_block\n   -npass numpass\n'
        # raise Exception('Indicate recording folder -r')
        folder = 'recordings/recording_eeg_16chan_ica.mat'
        block_size = 10
        ff = 'cooling'
        mu = 0.1
        oricamod = 'W_block'

    # else:
    if 'eeg' not in folder:
        recordings = np.load(join(folder, 'recordings.npy')).astype('int16')
        rec_info = [f for f in os.listdir(folder) if '.yaml' in f or '.yml' in f][0]
        with open(join(folder, rec_info), 'r') as f:
            info = yaml.load(f)
        electrode_name = info['General']['electrode name']
        mea_pos, mea_dim, mea_pitch = MEA.return_mea(electrode_name)

        templates = np.load(join(folder, 'templates.npy'))
        mixing = np.load(join(folder, 'mixing.npy')).T
        sources = np.load(join(folder, 'sources.npy'))
        adj_graph = extract_adjacency(mea_pos, np.max(mea_pitch) + 5)
    else:
        mat_contents = sio.loadmat(folder)
        recordings = mat_contents['recordings']
        mixing = mat_contents['mixing']
        times = mat_contents['times']
        sources = mat_contents['sources']
        mea_pos = mat_contents['pos']
        mea_pitch = [10, 10]
        mea_dim = [4, 4]
        adj_graph = extract_adjacency(mea_pos, 0.06)


    orica_type = oricamod # original - W - A -  W_block - A_block
    if ff == 'constant':
        lambda_val = 1. / recordings.shape[1] # 0.995
    else:
        lambda_val = lambda_val

    t_start = time.time()
    if mod == 'orica':
        if orica_type == 'original':
            ori = orica.ORICA(recordings, sphering='offline', forgetfac=ff, lambda_0=lambda_val,
                              mu=mu, verbose=True, numpass=npass, block_white=block_size, block_ica=block_size,
                              adjacency=adj_graph)
        elif orica_type == 'W':
            ori = orica.ORICA_W(recordings, sphering='offline', forgetfac=ff, lambda_0=lambda_val,
                                mu=mu, verbose=True, numpass=1, block_white=block_size, block_ica=block_size,
                                adjacency=adj_graph)
        elif orica_type == 'A':
            ori = orica.ORICA_A(recordings, sphering='offline', forgetfac=ff, lambda_0=lambda_val,
                                mu=mu, verbose=True, numpass=npass, block_white=block_size, block_ica=block_size,
                                adjacency=adj_graph)
        elif orica_type == 'W_block':
            ori = orica.ORICA_W_block(recordings, sphering='offline', forgetfac=ff, lambda_0=lambda_val,
                                      mu=mu, verbose=True, numpass=npass, block_white=block_size, block_ica=block_size,
                                      adjacency=adj_graph, regmode=reg)
        elif orica_type == 'A_block':
            ori = orica.ORICA_A_block(recordings, sphering='offline', forgetfac=ff, lambda_0=lambda_val,
                                      mu=mu, verbose=True, numpass=npass, block_white=block_size, block_ica=block_size,
                                      adjacency=adj_graph)
        else:
            raise Exception('ORICA type not understood')

        y = ori.y
        w = ori.unmixing
        m = ori.sphere
        a = ori.mixing

    elif mod == 'ica':
        y, a, w = ica.instICA(recordings)

    proc_time = time.time() - t_start
    print 'Processing time: ', proc_time

    if 'eeg' not in folder:
        # Skewness
        skew_thresh = 0.1
        sk = stats.skew(y, axis=1)
        high_sk = np.where(np.abs(sk) >= skew_thresh)

        # Kurtosis
        ku_thresh = 0.8
        ku = stats.kurtosis(y, axis=1)
        high_ku = np.where(np.abs(ku) >= ku_thresh)

        a_t = np.zeros(a.shape)
        for i, a_ in enumerate(a):
            if np.abs(np.min(a_)) > np.abs(np.max(a_)):
                a_t[i] = -a_ / np.max(np.abs(a_))
            else:
                a_t[i] = a_ / np.max(np.abs(a_))

        # Smoothness
        smooth = np.zeros(a.shape[0])
        for i in range(len(smooth)):
           smooth[i] = (np.mean([1. / len(adj) * np.sum(a_t[i, j] - a_t[i, adj]) ** 2
                                                 for j, adj in enumerate(adj_graph)]))


        print 'High skewness: ', np.abs(sk[high_sk])
        print 'Average high skewness: ', np.mean(np.abs(sk[high_sk]))
        print 'Number high skewness: ', len(sk[high_sk])

        print 'High kurtosis: ', ku[high_ku]
        print 'Average high kurtosis: ', np.mean(ku[high_ku])
        print 'Number high kurtosis: ', len(ku[high_ku])

        # print 'Smoothing: ', smooth[high_sk]
        print 'Average smoothing: ', np.mean(smooth[high_sk])

        # if plot_fig:
        #     plot_mixing(mixing.T, mea_pos, mea_dim)
        #     plot_mixing(a_t[high_sk], mea_pos, mea_dim)

        correlation, idx_truth, idx_orica, _ = matcorr(mixing.T, a[high_sk])
        sorted_idx = idx_orica[idx_truth.argsort()]
        sorted_corr_idx = idx_truth.argsort()
        # high_sk_a = a[high_sk]
        sorted_a = np.matmul(np.diag(np.sign(correlation[sorted_corr_idx])), a[high_sk][sorted_idx]).T
        sorted_mixing = mixing[:, np.sort(idx_truth)]
        sorted_y = np.matmul(np.diag(np.sign(correlation[sorted_corr_idx])), y[high_sk][sorted_idx])
        sorted_y_true = sources[np.sort(idx_truth)]
        average_corr = np.mean(np.abs(correlation[sorted_corr_idx]))

        PI, C = evaluate_PI(sorted_a.T, sorted_mixing)

        if plot_fig:
            plot_mixing(sorted_mixing.T, mea_pos, mea_dim)
            plot_mixing(sorted_a.T, mea_pos, mea_dim)

            # fig = plt.figure()
            # ax = fig.add_subplot(111)
            # colors = plt.rcParams['axes.color_cycle']
            # for i, (true_y, ica_y) in enumerate(zip(sorted_y_true, sorted_y)):
            #     ax.plot(true_y/np.max(np.abs(true_y)), alpha=0.3, color=colors[int(np.mod(i, len(colors)))])
            #     ax.plot(ica_y/np.max(np.abs(ica_y)), alpha=0.8, color=colors[int(np.mod(i, len(colors)))])

    else:
        a_t = np.zeros(a.shape)
        for i, a_ in enumerate(a):
            if np.abs(np.min(a_)) > np.abs(np.max(a_)):
                a_t[i] = -a_ / np.max(np.abs(a_))
            else:
                a_t[i] = a_ / np.max(np.abs(a_))

        # Smoothness (A is transpose already)
        smooth = np.zeros(a.shape[0])
        for i in range(len(smooth)):
            smooth[i] = np.sum([1. / len(adj) * np.sum(a_t[i, j] - a_t[i, adj]) ** 2
                                for j, adj in enumerate(adj_graph)])

        correlation, idx_truth, idx_orica, _ = matcorr(mixing.T, a)
        sorted_idx = idx_orica[idx_truth.argsort()]
        sorted_corr_idx = idx_truth.argsort()
        sorted_a = np.matmul(np.diag(np.sign(correlation[sorted_corr_idx])), a[sorted_idx]).T
        sorted_mixing = mixing[:, np.sort(idx_truth)]
        sorted_y = np.matmul(np.diag(np.sign(correlation[sorted_corr_idx])), y[sorted_idx])
        average_corr = np.mean(np.abs(correlation[sorted_corr_idx]))

        PI, C = evaluate_PI(w, mixing)

        if plot_fig:
            plot_topo_eeg(mixing.T, mea_pos)
            plot_topo_eeg(sorted_a.T, mea_pos)

    print 'Average smoothing: ', np.mean(smooth)
    print 'Performance index: ', PI
    print 'Average correlation: ', average_corr


    cc_sources = np.dot(sources, y.T)
    cc_mixing = np.dot(mixing.T, a.T)

    plt.ion()
    plt.show()


    # f = plot_mixing(a[high_sk], mea_pos, mea_dim)
    # f.suptitle('ORICA ' + orica_type + ' ' + str(block_size))
    # plt.figure();
    # plt.plot(y[high_sk].T)
    # plt.title('ORICA ' + orica_type + ' ' + str(block_size))