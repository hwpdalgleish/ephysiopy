#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Sep 27 12:08:10 2019

@author: robin
"""
import numpy as np
import os
import matplotlib.pylab as plt
from ephysiopy.dacq2py import axonaIO
from ephysiopy.ephys_generic.ephys_generic import PosCalcsGeneric
from ephysiopy.openephys2py import OEKiloPhy, OESettings
from scipy import signal
import h5py

class OE2Axona(object):
	"""

	"""
	def __init__(self, filename_root: str):
		self.filename_root = filename_root # '/home/robin/Data/experiment_1.nwb' or whatever
		self.dirname = os.path.dirname(filename_root) # '/home/robin/Data'
		self.experiment_name = os.path.basename(self.filename_root) # 'experiment_1.nwb'
		self.recording_name = None # will become 'recording1' etc
		self.OE_data = None # will become an instance of OEKiloPhy.OpenEphysNWB
		# Create a basename for Axona file names e.g.'/home/robin/Data/experiment_1'
		# that we can append '.pos' or '.eeg' or whatever onto
		self.axona_root_name = os.path.join(self.dirname, os.path.splitext(self.experiment_name)[0])
		self.AxonaData = axonaIO.IO(self.axona_root_name + ".pos") # need to instantiated now for later
		# THIS IS TEMPORARY AND WILL BE MORE USER-SPECIFIABLE IN THE FUTURE
		# it is used to scale the spikes
		self.gain = 500
		self.bitvolts = 0.195

	def upsample(self, data, src_rate=30, dst_rate=50, axis=0):
		'''
		Upsamples data using FFT
		'''
		denom = np.gcd(dst_rate, src_rate)
		new_data = signal.resample_poly(data, dst_rate/denom, src_rate/denom, axis)
		return new_data

	def getOEData(self, filename_root: str, recording_name='recording1')->dict:
		'''
		Loads the nwb file names in filename_root and returns a dict containing some of the nwb data
		relevant for converting to Axona file formats

		Parameters
		----------------
		filename_root - fuly qualified name of the nwb file
		recording_name - the name of the recording in the nwb file NB the default has changed in different versions of OE from 'recording0' to 'recording1'
		'''
		if os.path.isfile(filename_root):
			root_filename = os.path.splitext(self.experiment_name)[0]
			OE_data = OEKiloPhy.OpenEphysNWB(self.dirname)
			print("Loading nwb data...")
			OE_data.load(session_name=self.experiment_name, recording_name=recording_name, loadspikes=True, loadraw=False)
			print("Loaded nwb data from: {}".format(filename_root))
			# It's likely that spikes have been collected after the last position sample
			# due to buffering issues I can't be bothered to resolve. Get the last pos
			# timestamps here and check that spikes don't go beyond this when writing data
			# out later
			# Also the pos and spike data timestamps almost never start at 0 as the user
			# usually acquires data for a while before recording. Grab the first timestamp
			# here with a view to subtracting this from everything (including the spike data)
			# and figuring out what to keep later
			first_pos_ts = OE_data.xyTS[0]
			last_pos_ts = OE_data.xyTS[-1]
			self.first_pos_ts = first_pos_ts
			self.last_pos_ts = last_pos_ts
			self.recording_name = recording_name
			self.OE_data = OE_data
			return OE_data

	def exportPos(self, ppm=300, jumpmax=100):
		#
		# Step 1) Deal with the position data first:
		#
		# Grab the settings of the pos tracker and do some post-processing on the position
		# data (discard jumpy data, do some smoothing etc)
		settings = OESettings.Settings(os.path.join(self.dirname, 'settings.xml'))
		settings.parsePos()
		posProcessor = PosCalcsGeneric(self.OE_data.xy[:,0], self.OE_data.xy[:,1], ppm, True, jumpmax)
		print("Post-processing position data...")
		xy, _ = posProcessor.postprocesspos(settings.tracker_params)
		xy = xy.T
		# Do the upsampling of both xy and the timestamps
		print("Beginning export of position data to Axona format...")
		axona_pos_file_name = self.axona_root_name + ".pos"
		axona_pos_data = self.convertPosData(xy, self.OE_data.xyTS)
		# Create an empty header for the pos data
		pos_header = self.AxonaData.getEmptyHeader("pos")
		for key in pos_header.keys():
			if 'min_x' in key:
				pos_header[key] = str(settings.tracker_params['LeftBorder'])
			if 'min_y' in key:
				pos_header[key] = str(settings.tracker_params['TopBorder'])
			if 'max_x' in key:
				pos_header[key] = str(settings.tracker_params['RightBorder'])
			if 'max_y' in key:
				pos_header[key] = str(settings.tracker_params['BottomBorder'])
		pos_header['duration'] = str(np.ceil(self.last_pos_ts - self.first_pos_ts).astype(np.int))
		# Rest of this stuff probably won't change so should be defaulted in the loaded file
		# (see axonaIO.py)
		pos_header['num_colours'] = '4'
		pos_header['sw_version'] = '1.2.2.1'
		pos_header['timebase'] = '50 hz'
		pos_header['sample_rate'] = '50.0 hz'
		pos_header['pos_format'] = 't,x1,y1,x2,y2,numpix1,numpix2'
		pos_header['bytes_per_coord'] = '2'
		pos_header['EEG_samples_per_position'] = '5'
		pos_header['bytes_per_timestamp'] = '4'
		pos_header['pixels_per_metre'] = str(ppm)
		pos_header['num_pos_samples'] = str(len(axona_pos_data))
		pos_header['bearing_colour_1'] = '210'
		pos_header['bearing_colour_2'] = '30'
		pos_header['bearing_colour_3'] = '0'
		pos_header['bearing_colour_4'] = '0'
		pos_header['pixels_per_metre'] = str(ppm)

		self.writePos2AxonaFormat(pos_header, axona_pos_data)
		print("Exported position data to Axona format")

	def exportSpikes(self):
		print("Beginning conversion of spiking data...")
		self.convertSpikeData(self.OE_data.nwbData['acquisition']['timeseries'][self.recording_name]['spikes'])
		print("Completed exporting spiking data")

	def convertPosData(self, xy: np.array, xy_ts: np.array):
		'''
		Perform the conversion of the array parts of the data
		NB As well as upsampling the data to the Axona pos sampling rate (50Hz)
		we have to insert some columns into the pos array as Axona format expects it like:
		pos_format: t,x1,y1,x2,y2,numpix1,numpix2
		We can make up some of the info and ignore other bits
		'''
		n_new_pts = int(np.floor((self.last_pos_ts-self.first_pos_ts) * 50))
		t = xy_ts - self.first_pos_ts
		new_ts = np.linspace(t[0], t[-1], n_new_pts)
		new_x = np.interp(new_ts, t, xy[:, 0])
		new_y = np.interp(new_ts, t, xy[:, 1])
		# Expand the pos bit of the data to be returned to make it look like Axona data
		new_pos = np.vstack([new_x, new_y]).T
		new_pos = np.c_[new_pos, np.ones_like(new_pos) * 1023, np.zeros_like(new_pos), np.zeros_like(new_pos)]
		new_pos[:, 4] = 40 # just made this value up - it's numpix i think
		new_pos[:, 6] = 40 # same
		# Squeeze this data into Axona pos format array
		dt = self.AxonaData.axona_files['.pos']
		new_data = np.zeros(n_new_pts, dtype=dt)
		# Timestamps in Axona are time in seconds * sample_rate
		new_data['ts'] = new_ts * 50
		new_data['pos'] = new_pos
		return new_data

	def convertSpikeData(self, hdf5_tetrode_data: h5py._hl.group.Group):
		'''
		Does the spike conversion from OE Spike Sorter format to Axona format tetrode files

		Parameters
		-----------
		hdf5_tetrode_data - h5py._hl.group.Group - this kind of looks like a dictionary and can, it seems,
								be treated as one more or less (see http://docs.h5py.org/en/stable/high/group.html).
		'''
		# First lets get the datatype for tetrode files as this will be the same for all tetrodes...
		dt = self.AxonaData.axona_files['.1']
		# ... and a basic header for the tetrode file that use for each tetrode file, changing only the num_spikes value
		header = self.AxonaData.getEmptyHeader("tetrode")
		header['duration'] = str(int(self.last_pos_ts-self.first_pos_ts))
		header['sw_version'] = '1.1.0'
		header['num_chans'] = '4'
		header['timebase'] = '96000 hz'
		header['bytes_per_timestamp'] = '4'
		header['samples_per_spike'] = '50'
		header['sample_rate'] = '48000 hz'
		header['bytes_per_sample'] = '1'
		header['spike_format'] = 't,ch1,t,ch2,t,ch3,t,ch4'

		for key in hdf5_tetrode_data.keys():
			spiking_data = np.array(hdf5_tetrode_data[key].get('data'))
			timestamps = np.array(hdf5_tetrode_data[key].get('timestamps'))
			# check if any of the spiking data is captured before/ after the first/ last bit of position data
			# if there is then discard this as we potentially have no valid position to align the spike to :(
			idx = np.logical_or(timestamps < self.first_pos_ts, timestamps > self.last_pos_ts)
			spiking_data = spiking_data[~idx, :, :]
			timestamps = timestamps[~idx]
			# subtract the first pos timestamp from the spiking timestamps
			timestamps = timestamps - self.first_pos_ts
			# get the number of spikes here for use below in the header
			num_spikes = len(timestamps)
			# repeat the timestamps in tetrode multiples ready for Axona export
			new_timestamps = np.repeat(timestamps, 4)
			new_spiking_data = spiking_data.astype(np.float64)
			# Convert to microvolts...
			new_spiking_data = new_spiking_data * self.bitvolts
			# And upsample the spikes...
			new_spiking_data = self.upsample(new_spiking_data, 4, 5, -1)
			# ... and scale appropriately for Axona and invert as OE seems to be inverted wrt Axona
			new_spiking_data = new_spiking_data / (self.gain/4/128.0) * (-1)
			# ... scale them to the gains specified somewhere (not sure where / how to do this yet)
			shp = new_spiking_data.shape
			# then reshape them as Axona wants them a bit differently
			new_spiking_data = np.reshape(new_spiking_data, [shp[0] * shp[1], shp[2]])
			# Cap any values outside the range of int8
			new_spiking_data[new_spiking_data < -128] = -128
			new_spiking_data[new_spiking_data > 127] = 127
			# create the new array
			new_tetrode_data = np.zeros(len(new_timestamps), dtype=dt)
			new_tetrode_data['ts'] = new_timestamps * 96000
			new_tetrode_data['waveform'] = new_spiking_data
			# change the header num_spikes field
			header['num_spikes'] = str(num_spikes)
			i_tetnum = key.split('electrode')[1]
			print("Exporting tetrode {}".format(i_tetnum))
			self.writeTetrodeData(i_tetnum, header, new_tetrode_data)

	def makeLFPData(self, hdf5_continuous_data: np.array, channel: int, eeg_type='eeg'):
		'''
		Downsamples the row denoted by channel in hdf5_continuous_data and saves the result
		as either an egf or eeg file depending on the choice of either eeg_type which can
		take a value of either 'egf' or 'eeg'
		'''
		if eeg_type == 'eeg':
			dt = self.AxonaData.axona_files['.eeg']
			header = self.AxonaData.getEmptyHeader("eeg")
		else if eeg_type == 'egf':
			dt = self.AxonaData.axona_files['.egf']
			header = self.AxonaData.getEmptyHeader("egf")
		


	def writePos2AxonaFormat(self, header:  dict, data: np.array):
		self.AxonaData.setHeader(self.axona_root_name + ".pos", header)
		self.AxonaData.setData(self.axona_root_name + ".pos", data)

	def writeTetrodeData(self, tetnum: str, header: dict, data: np.array):
		self.AxonaData.setHeader(self.axona_root_name + "." + tetnum, header)
		self.AxonaData.setData(self.axona_root_name + "." + tetnum, data)