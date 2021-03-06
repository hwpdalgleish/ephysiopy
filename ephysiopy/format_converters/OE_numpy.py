"""
openephys to numpy file conversion 
"""
import numpy as np
import os
import matplotlib.pylab as plt
from ephysiopy.dacq2py import axonaIO
from ephysiopy.common.ephys_generic import PosCalcsGeneric
from ephysiopy.openephys2py import OEKiloPhy, OESettings
from scipy import signal
import h5py

class OE2Numpy(object):
	"""
	Converts openephys data recorded in the nwb format into numpy files

	NB Only exports the LFP and TTL files at the moment
	"""
	def __init__(self, filename_root: str):
		self.filename_root = filename_root # '/home/robin/Data/experiment_1.nwb' or whatever
		self.dirname = os.path.dirname(filename_root) # '/home/robin/Data'
		self.experiment_name = os.path.basename(self.filename_root) # 'experiment_1.nwb'
		self.recording_name = None # will become 'recording1' etc
		self.OE_data = None # will become an instance of OEKiloPhy.OpenEphysNWB
		self._settings = None # will become an instance of OESettings.Settings
		self.fs = None
		self.lfp_lowcut = None
		self.lfp_highcut = None

	def resample(self, data, src_rate=30, dst_rate=50, axis=0):
		"""
		Upsamples data using FFT
		"""
		denom = np.gcd(dst_rate, src_rate)
		new_data = signal.resample_poly(data, dst_rate/denom, src_rate/denom, axis)
		return new_data

	@property
	def settings(self):
		"""
		Loads the settings data from the settings.xml file
		"""
		if self._settings is None:
			self._settings = OESettings.Settings(self.dirname)
		return self._settings

	@settings.setter
	def settings(self, value):
		self._settings = value

	def getOEData(self, filename_root: str, recording_name='recording1')->dict:
		"""
		Loads the nwb file names in filename_root and returns a dict containing some of the nwb data
		relevant for converting to Axona file formats

		Parameters
		----------------
		filename_root - fuly qualified name of the nwb file
		recording_name - the name of the recording in the nwb file NB the default has changed in different versions of OE from 'recording0' to 'recording1'
		"""
		if os.path.isfile(filename_root):
			OE_data = OEKiloPhy.OpenEphysNWB(self.dirname)
			print("Loading nwb data...")
			OE_data.load(self.dirname, session_name=self.experiment_name, recording_name=recording_name, loadspikes=False, loadraw=True)
			print("Loaded nwb data from: {}".format(filename_root))
			# It's likely that spikes have been collected after the last position sample
			# due to buffering issues I can't be bothered to resolve. Get the last pos
			# timestamps here and check that spikes don't go beyond this when writing data
			# out later
			# Also the pos and spike data timestamps almost never start at 0 as the user
			# usually acquires data for a while before recording. Grab the first timestamp
			# here with a view to subtracting this from everything (including the spike data)
			# and figuring out what to keep later
			try: # pos might not be present
				first_pos_ts = OE_data.xyTS[0]
				last_pos_ts = OE_data.xyTS[-1]
				self.first_pos_ts = first_pos_ts
				self.last_pos_ts = last_pos_ts
			except:
				print("No position data in nwb file")
			self.recording_name = recording_name
			self.OE_data = OE_data
			return OE_data

	def exportLFP(self, channels: list, output_freq: int):
		print("Beginning conversion and exporting of LFP data...")
		channels = [int(c) for c in channels]
		if self.settings.fpga_nodeId is None:
			self.settings.parse()
		if self.settings.fpga_sample_rate is None:
			self.settings.parseChannels()
		output_name = os.path.join(self.dirname, "lfp.npy")
		output_ts_name = os.path.join(self.dirname, "lfp_timestamps.npy")
		if len(channels) == 1:
			# resample data
			print("Resampling data from {0} to {1} Hz".format(self.settings.fpga_sample_rate, output_freq))
			new_data = self.resample(self.OE_data.rawData[:, channels], self.settings.fpga_sample_rate, output_freq)
			np.save(output_name, new_data, allow_pickle=False)
		if len(channels) > 1:
			print("Resampling data from {0} to {1} Hz".format(self.settings.fpga_sample_rate, output_freq))
			new_data = self.resample(self.OE_data.rawData[:, channels[0]:channels[-1]], self.settings.fpga_sample_rate, output_freq)
			np.save(output_name, new_data, allow_pickle=False)
		nsamples = np.shape(new_data)[0]
		new_ts = np.linspace(self.OE_data.ts[0], self.OE_data.ts[-1], nsamples)
		np.save(output_ts_name, new_ts, allow_pickle=False)
		print("Finished exporting LFP data")

	def exportTTL(self):
		print("Exporting TTL data...")
		ttl_state = self.OE_data.ttl_data
		ttl_ts = self.OE_data.ttl_timestamps
		np.save(os.path.join(self.dirname, "ttl_state.npy"), ttl_state, allow_pickle=False)
		np.save(os.path.join(self.dirname, "ttl_timestamps.npy"), ttl_ts, allow_pickle=False)
		print("Finished exporting TTL data")