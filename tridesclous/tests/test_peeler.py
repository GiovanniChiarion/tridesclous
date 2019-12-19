import pytest

from tridesclous import *

import numpy as np
import scipy.signal
import time
import os
import shutil

import  pyqtgraph as pg

from tridesclous.dataio import DataIO
from tridesclous.catalogueconstructor import CatalogueConstructor
from tridesclous import Peeler
from tridesclous.peeler_cl import Peeler_OpenCl

from tridesclous.peakdetector import  detect_peaks_in_chunk


from tridesclous.tests.testingtools import setup_catalogue
from tridesclous.tests.testingtools import ON_CI_CLOUD




def setup_module():
    setup_catalogue('test_peeler', dataset_name='olfactory_bulb')

def teardown_module():
    shutil.rmtree('test_peeler')


def open_catalogue_window():
    dataio = DataIO(dirname='test_peeler')
    catalogueconstructor = CatalogueConstructor(dataio=dataio)
    app = pg.mkQApp()
    win = CatalogueWindow(catalogueconstructor)
    win.show()
    app.exec_()

@pytest.mark.first
def test_peeler_classic():
    dataio = DataIO(dirname='test_peeler')
    catalogue = dataio.load_catalogue(chan_grp=0)

    peeler = Peeler(dataio)
    
    peeler.change_params(engine='classic', catalogue=catalogue,chunksize=1024)
    
    t1 = time.perf_counter()
    peeler.run(progressbar=False)
    t2 = time.perf_counter()
    print('peeler.run_loop', t2-t1)

    
    spikes = dataio.get_spikes(chan_grp=0).copy()
    labels = catalogue['clusters']['cluster_label']
    count_by_label = [np.sum(spikes['cluster_label'] == label) for label in labels]
    print(labels)
    print(count_by_label)
    

def test_peeler_geometry():
    dataio = DataIO(dirname='test_peeler')
    catalogue = dataio.load_catalogue(chan_grp=0)

    peeler = Peeler(dataio)

    peeler.change_params(engine='geometrical',
                                catalogue=catalogue,
                                chunksize=1024,
                                use_sparse_template=True,
                                sparse_threshold_mad=1.5,
                                argmin_method='numba')
                                

    t1 = time.perf_counter()
    peeler.run(progressbar=False)
    t2 = time.perf_counter()
    print('peeler.run_loop', t2-t1)


    spikes = dataio.get_spikes(chan_grp=0).copy()
    labels = catalogue['clusters']['cluster_label']
    count_by_label = [np.sum(spikes['cluster_label'] == label) for label in labels]
    print(labels)
    print(count_by_label)



@pytest.mark.skipif(ON_CI_CLOUD, reason='ON_CI_CLOUD')
def test_peeler_argmin_methods():
    dataio = DataIO(dirname='test_peeler')
    initial_catalogue = dataio.load_catalogue(chan_grp=0)
    
    argmin_methods = ['opencl', 'pythran', 'numba']
    #~ argmin_methods = ['opencl', 'pythran']
    
    for argmin_method in argmin_methods:
        
        peeler = Peeler(dataio)
        
        peeler.change_params(engine='classic',
                                            catalogue=initial_catalogue,
                                            chunksize=1024,
                                            use_sparse_template=True,
                                            sparse_threshold_mad=1.5,
                                            argmin_method=argmin_method,
                                            cl_platform_index=0,
                                            cl_device_index=0,                                        
                                            )
        
        t1 = time.perf_counter()
        peeler.run(progressbar=False)
        t2 = time.perf_counter()
        print(argmin_method ,'peeler.run_loop', t2-t1)



    

def test_peeler_empty_catalogue():
    """
    This test peeler with empty catalogue.
    This is like a peak detector.
    Check several chunksize and compare to offline-one-buffer.
    
    """
    dataio = DataIO(dirname='test_peeler')
    #~ print(dataio)
    catalogue = dataio.load_catalogue(chan_grp=0)
    
    # empty catalogue for debug peak detection
    s = catalogue['centers0'].shape
    empty_centers = np.zeros((0, s[1], s[2]), dtype='float32')
    catalogue['centers0'] = empty_centers
    catalogue['centers1'] = empty_centers
    catalogue['centers2'] = empty_centers
    catalogue['cluster_labels'] = np.zeros(0, dtype=catalogue['cluster_labels'].dtype)
        
    
    sig_length = dataio.get_segment_length(0)
    chunksizes = [ 101, 174, 512, 1024, 1023, 10000, 150000]
    #~ chunksizes = [1024,]
    
    previous_peak = None
    
    for chunksize in chunksizes:
        print('**',  chunksize, '**')
        peeler = Peeler(dataio)
        peeler.change_params(engine='classic', catalogue=catalogue,chunksize=chunksize)
        t1 = time.perf_counter()
        #~ peeler.run(progressbar=False)
        peeler.run_offline_loop_one_segment(seg_num=0, progressbar=False)
        t2 = time.perf_counter()
        
        #~ print('n_side', peeler.n_side, 'n_span', peeler.n_span, 'peak_width', peeler.peak_width)
        #~ print('peeler.run_loop', t2-t1)
        
        spikes = dataio.get_spikes(seg_num=0, chan_grp=0)
        labeled_spike = spikes[spikes['cluster_label']>=0]
        unlabeled_spike = spikes[spikes['cluster_label']<0]
        assert labeled_spike.size == 0
        
        is_sorted = np.all(np.diff(unlabeled_spike['index'])>=0)
        assert is_sorted
        
        
        online_peaks = unlabeled_spike['index']
        engine = peeler.peeler_engine
        
        i_stop = sig_length-catalogue['signal_preprocessor_params']['lostfront_chunksize']-engine.extra_size+engine.n_span
        sigs = dataio.get_signals_chunk(signal_type='processed', i_stop=i_stop)
        offline_peaks  = detect_peaks_in_chunk(sigs, engine.n_span, engine.relative_threshold, engine.peak_sign)
        
        offline_peaks  = offline_peaks[offline_peaks<=online_peaks[-1]]
        
        assert offline_peaks.size == online_peaks.size
        np.testing.assert_array_equal(offline_peaks, online_peaks)
        
        if previous_peak is not None:
            last = min(previous_peak[-1], online_peaks[-1])
            previous_peak = previous_peak[previous_peak<=last]
            online_peaks_cliped = online_peaks[online_peaks<=last]
            assert  previous_peak.size == online_peaks_cliped.size
            np.testing.assert_array_equal(previous_peak, online_peaks_cliped)
        
        previous_peak = online_peaks
        


@pytest.mark.skipif(ON_CI_CLOUD, reason='To hard for CI')
def test_peeler_several_chunksize():
    
    dataio = DataIO(dirname='test_peeler')
    print(dataio)
    catalogue = dataio.load_catalogue(chan_grp=0)
    
    
    all_spikes = []
    sig_length = dataio.get_segment_length(0)
    chunksizes = [ 174, 512, 1024, 1023, 10000, 150000]
    #~ chunksizes = [512, 1024,]
    for chunksize in chunksizes:
        print('**',  chunksize, '**')
        peeler = Peeler(dataio)
        peeler.change_params(engine='classic', catalogue=catalogue,chunksize=chunksize)
        t1 = time.perf_counter()
        peeler.run_offline_loop_one_segment(seg_num=0, progressbar=False)
        t2 = time.perf_counter()
        print('extra_size', peeler.peeler_engine.extra_size, 'n_span', peeler.peeler_engine.n_span,
                        'peak_width', peeler.peeler_engine.peak_width)
        print('peeler.run_loop', t2-t1)
        
        # copy is need because the memmap is reset at each loop
        spikes = dataio.get_spikes(seg_num=0, chan_grp=0).copy()
        all_spikes.append(spikes)
        print(spikes.size)
    
    
    # clip to last spike
    last = min([spikes[-1]['index'] for spikes in all_spikes])
    for i, chunksize in enumerate(chunksizes):
        spikes = all_spikes[i]
        all_spikes[i] = spikes[spikes['index']<=last]
    
    previsous_spikes = None
    for i, chunksize in enumerate(chunksizes):
        print('**',  chunksize, '**')
        spikes = all_spikes[i]
        is_sorted = np.all(np.diff(spikes['index'])>=0)
        assert is_sorted
        
        labeled_spike = spikes[spikes['cluster_label']>=0]
        unlabeled_spike = spikes[spikes['cluster_label']<0]
        print('labeled_spike.size', labeled_spike.size, 'unlabeled_spike.size', unlabeled_spike.size)
        print(spikes)
        
        # TODO: Peeler chunksize influence the number of spikes
        
        if previsous_spikes is not None:
            assert  previsous_spikes.size == spikes.size
            np.testing.assert_array_equal(previsous_spikes['index'], spikes['index'])
            np.testing.assert_array_equal(previsous_spikes['cluster_label'], spikes['cluster_label'])
        
        previsous_spikes = spikes

def open_PeelerWindow():
    dataio = DataIO(dirname='test_peeler')
    initial_catalogue = dataio.load_catalogue(chan_grp=0)

    app = pg.mkQApp()
    win = PeelerWindow(dataio=dataio, catalogue=initial_catalogue)
    win.show()
    app.exec_()


def test_export_spikes():
    dataio = DataIO(dirname='test_peeler')
    dataio.export_spikes()




#~ def test_peeler_cl():
    #~ dataio = DataIO(dirname='test_peeler')
    #~ initial_catalogue = dataio.load_catalogue(chan_grp=0)

    #~ peeler = Peeler(dataio)
    
    #~ peeler.change_params(engine='classic_opencl', catalogue=initial_catalogue,chunksize=1024)
    
    #~ t1 = time.perf_counter()
    #~ peeler.run(progressbar=False)
    #~ t2 = time.perf_counter()
    #~ print('peeler_cl.run_loop', t2-t1)




def debug_compare_peeler_engines():

    dataio = DataIO(dirname='test_peeler')
    print(dataio)
    
    
    engine_list = [ 
            ('classic argmin numpy', 'classic', {'argmin_method' : 'numpy', 'use_sparse_template':False}),
            ('classic argmin cl', 'classic', {'argmin_method' : 'opencl', 'use_sparse_template':True}),
            ('geometrical argmin opencl', 'classic', {'argmin_method' : 'opencl', 'use_sparse_template':True}),
        ]
    
    all_spikes =  []
    for name, engine, kargs in engine_list:
        #~ print()
        #~ print(name)
        catalogue = dataio.load_catalogue(chan_grp=0)


        peeler = Peeler(dataio)
        peeler.change_params(engine=engine, catalogue=catalogue,chunksize=1024, **kargs)

        t1 = time.perf_counter()
        peeler.run(progressbar=False, duration=None)
        t2 = time.perf_counter()
        print(name, 'run', t2-t1)
        
        
        spikes = dataio.get_spikes(chan_grp=0).copy()
        #~ print(spikes.size)
        all_spikes.append(spikes)
        
        
        #~ print(dataio.get_spikes(chan_grp=0).size)
    
    print()
    #~ all_spikes[0] = all_spikes[0][88+80:88+81+10]
    #~ all_spikes[1] = all_spikes[1][88+80:88+81+10]

    #~ all_spikes[0] = all_spikes[0][:88+81]
    #~ all_spikes[1] = all_spikes[1][:88+81]
    
    labels = catalogue['clusters']['cluster_label']
    
    for i, spikes in enumerate(all_spikes):
        name = engine_list[i][0]
        print()
        print(name)
        print(spikes[:10])
        print(spikes.size)
        
        count_by_label = [np.sum(spikes['cluster_label'] == label) for label in labels]
        print(count_by_label)
            
        
        #~ assert all_spikes[0].size == spikes.size
        #~ assert np.all(all_spikes[0]['index'] == spikes['index'])
        #~ assert np.all(all_spikes[0]['cluster_label'] == spikes['cluster_label'])
        #~ assert np.all(np.abs(all_spikes[0]['jitter'] - spikes['jitter'])<0.0001)
    
    
if __name__ =='__main__':
    #~ setup_module()
    
    #~ open_catalogue_window()
    
    #~ test_peeler_classic()
    
    test_peeler_geometry()
    
    #~ test_peeler_cl()
    
    #~ test_peeler_argmin_methods()
    
    #~ test_peeler_empty_catalogue()
    
    #~ test_peeler_several_chunksize()
    
    #~ test_export_spikes()
    
    
    #~ debug_compare_peeler_engines()
    
    #~ open_PeelerWindow()
    
    #~ teardown_module()
