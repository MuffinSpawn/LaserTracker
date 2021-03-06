# -*- coding: utf-8 -*-
"""
Created on Thu Feb  1 16:05:49 2018

@author: Peter G. Lane (petergwinlane@gmail.com)
"""

import argparse
import collections
import csv
import logging
import math
import numpy
import numpy.linalg as linalg
import os
import signal
import sys
import platform
import time
import tkinter as tk
import tkinter.filedialog as tkfile
import tkinter.ttk as ttk

import CESAPI.connection
import CESAPI.command
from CESAPI.packet import *
import CESAPI.refract

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def signal_handler(signal, frame):
        print('You pressed Ctrl+C!')
        sys.exit(0)

class MeasurementSet(collections.Sequence):
    def __init__(self, command, num_measurements=0, labels=[], label_entry=None, rialg=CESAPI.refract.RI_ALG_Leica):
        self.__command = command
        self.__measurements = numpy.ndarray((num_measurements, 3))
        self.__labels = labels
        self.__label_entry = label_entry
        self.__refraction_index_algorithm = CESAPI.refract.AlgorithmFactory().refractionIndexAlgorithm(rialg)

    def __len__(self):
        return numpy.shape(self.__measurements)[0]

    def __getitem__(self, measurement_index):
        return self.__measurements[measurement_index]

    def __str__(self):
        stringlets = []
        for label,measurement in zip(self.__labels,self.__measurements):
            stringlets.append('{},{},{},{}'.format(label, *measurement))
        return '\n'.join(stringlets)

    def labels(self):
        return list(self.__labels)

    def measure(self, index=-1, append=False):
        coordinate_system_type = self.__command.GetCoordinateSystemType().coordSysType
        if coordinate_system_type != ES_CS_RHR:
            logger.debug('setting coordinate system type to Right-Handed Rectangular...')
            self.__command.SetCoordinateSystemType(ES_CS_RHR)  # one of ES_CoordinateSystemType
        measurement = measurement_to_array(measure(self.__command, rialg=self.__refraction_index_algorithm))
        logger.debug('Measurement array:\n{}'.format(measurement))
        if append:
            # determine what the label should be
            label = 'REFLECTOR#{}'.format(numpy.shape(self.__measurements)[0])
            if self.__label_entry != None:
                label = self.__label_entry.get()

            # replace or append the measurement and its label
            try:
                logger.debug('Replacing measurement...')
                index = self.__labels.index(label)
                self.__measurements[index] = measurement[:3]
            except ValueError:
                logger.debug('Appending measurement...')
                self.__labels.append(label)
                self.__measurements = numpy.vstack((self.__measurements, measurement[:3]))
        else:
            self.__measurements[index] = measurement[:3]
            if len(self.__labels) >= index:
                self.__labels[index].configure(background='green')
                self.__labels[index].configure(foreground='white')
        logger.debug('MeasurementSet after measure():\n{}'.format(self))

def calculate_approx_LTCS(cartesian_DSCS, transform_matrix):
    ones = numpy.ones(numpy.shape(cartesian_DSCS)[0])
    X = numpy.vstack([ones, cartesian_DSCS.transpose()])
    return numpy.dot(transform_matrix, X)[1:,:].transpose()

def cartesian_to_spherical(cartesian_LTCS):
    spherical_LTCS = numpy.ndarray(numpy.shape(cartesian_LTCS))
    for index,cartesian_point in enumerate(cartesian_LTCS):
        spherical_LTCS[index,2] = math.sqrt(numpy.sum(cartesian_point**2))
        spherical_LTCS[index,0] = math.atan2(cartesian_point[1], cartesian_point[0])
        spherical_LTCS[index,1] = math.acos(cartesian_point[2]/spherical_LTCS[index,2])
    return spherical_LTCS

def cartesian_to_cylindrical(cartesian_DSCS):
    cylindrical_DSCS = numpy.ndarray(numpy.shape(cartesian_DSCS))
    for index,cartesian_point in enumerate(cartesian_DSCS):
        cylindrical_DSCS[index,0] = math.sqrt(numpy.sum(cartesian_point[:2]**2))
        cylindrical_DSCS[index,1] = math.atan2(cartesian_point[1], cartesian_point[0])
        cylindrical_DSCS[index,2] = cylindrical_DSCS[index,2]
    return cylindrical_DSCS

def measurement_to_array(measurement):
    measurement_array = numpy.ndarray(9)
    measurement_array[0] = measurement.dVal1
    measurement_array[1] = measurement.dVal2
    measurement_array[2] = measurement.dVal3
    measurement_array[3] = measurement.dStd1
    measurement_array[4] = measurement.dStd2
    measurement_array[5] = measurement.dStd3
    measurement_array[6] = measurement.dTemperature
    measurement_array[7] = measurement.dPressure
    measurement_array[8] = measurement.dHumidity
    return measurement_array

def generate_ref_data_filenames(ref_network_DSCS_filename):
    ext_index = ref_network_DSCS_filename.rfind('.')
    transform_filename = ref_network_DSCS_filename[:ext_index] + '_transform.csv'
    inv_transform_filename = ref_network_DSCS_filename[:ext_index] + '_inv_transform.csv'
    ref_network_LTCS_filename = ref_network_DSCS_filename[:ext_index] + '_LTCS.csv'
    return (transform_filename, inv_transform_filename, ref_network_LTCS_filename)

def generate_data_filename(network_DSCS_filename):
    ext_index = network_DSCS_filename.rfind('.')
    ref_network_LTCS_filename = network_DSCS_filename[:ext_index] + '_LTCS.csv'
    return ref_network_LTCS_filename

def load_DSCS_coordinates(filename):
    with open(filename, 'r') as file:
        string_data = list(csv.reader(file, delimiter=','))

    reflector_names = []
    cylindrical_reflector_coordinates = numpy.ndarray((len(string_data), 3))
    for index,row in enumerate(string_data):
        reflector_names.append(row[0])
        point = list(map(lambda x: float(x), row[1:]))
        cylindrical_reflector_coordinates[index,:] = point

    cartesian_reflector_coordinates = numpy.ndarray((len(string_data), 3))
    for index,point in enumerate(cylindrical_reflector_coordinates):
        cartesian_reflector_coordinates[index,0] = point[0] * math.cos(point[1])
        cartesian_reflector_coordinates[index,1] = point[0] * math.sin(point[1])
        cartesian_reflector_coordinates[index,2] = point[2]
    return (numpy.array(reflector_names), cylindrical_reflector_coordinates, cartesian_reflector_coordinates)

def load_matrix(filename):
    with open(filename, 'r') as file:
        string_data = list(csv.reader(file, delimiter=','))


    matrix = numpy.ndarray((4,4))
    for index,row in enumerate(string_data):
        matrix[index,:] = numpy.array(list(map(lambda x: float(x), row)))
    return matrix

def save_matrix(filename, matrix):
    with open(filename, 'w') as file:
        for row in matrix:
            line = ','.join(map(str, row)) + '\n'
            file.write(line)

def load_coordinates(filename):
    with open(filename, 'r') as file:
        string_data = list(csv.reader(file, delimiter=','))

    reflector_names = []
    coordinates = numpy.ndarray((len(string_data), 3))
    for index,row in enumerate(string_data):
        reflector_names.append(row[0])
        point = list(map(lambda x: float(x), row[1:]))
        coordinates[index,:] = point
    return reflector_names, coordinates

def save_coordinates(filename, names, coordinates):
    with open(filename, 'w') as file:
        for name,point in zip(names, coordinates):
            row = numpy.hstack((name, point))
            line = ','.join(map(str, row)) + '\n'
            file.write(line)

def set_status(status_label, text):
    if status_label != None:
        status_label.configure(text=text)

def initialize(command, forceinit=False, manualiof=False, status_label=None):
    units = SystemUnitsDataT()
    units.lenUnitType = ES_LU_Millimeter  # ES_LengthUnit
    # units.angUnitType = ES_AU_Radian  # ES_AngleUnit
    # units.tempUnitType = ES_TU_Celsius  # ES_TemperatureUnit
    # units.pressUnitType = ES_PU_Mbar  # ES_PressureUnit
    # units.humUnitType = ES_HU_RH  # ES_HumidityUnit
    set_status(status_label, 'Setting units...')
    command.SetUnits(units)
    
    status = command.GetSystemStatus()
    logger.debug('Tracker Processor Status: {}'.format(status.trackerProcessorStatus))
    if forceinit or status.trackerProcessorStatus != ES_TPS_Initialized:  # ES_TrackerProcessorStatus
        set_status(status_label, 'Initializing...')
        command.Initialize()
        # At least the AT401 seems to complain about an unknown command failing due to "the sensor" not being stable
        # on the next command after an initialize. The tracker is fine after that, so just ignore this as a bug in the firmware.
        try:
            status = command.GetSystemStatus()
            logger.debug('Tracker Processor Status: {}'.format(status.trackerProcessorStatus))
        except Exception as e:
            if not 'Command 64' in str(e):
                raise e
    
    set_status(status_label, 'Setting measurement mode...')
    command.SetMeasurementMode(ES_MM_Stationary)  # ES_MeasMode (only choice for AT4xx)

    set_status(status_label, 'Setting stationary mode parameters...')
    mode_params = StationaryModeDataT()
    mode_params.lMeasTime = 1000  # 1 second
    command.SetStationaryModeParams(mode_params)

    set_status(status_label, 'Setting system settings...')
    settings = SystemSettingsDataT()
    # one of ES_WeatherMonitorStatus
    if manualiof:
        settings.weatherMonitorStatus = ES_WMS_ReadOnly
    else:
        settings.weatherMonitorStatus = ES_WMS_ReadAndCalculateRefractions
    settings.bApplyStationOrientationParams = int(1)
    settings.bKeepLastPosition = int(1)
    settings.bSendUnsolicitedMessages = int(1)
    settings.bSendReflectorPositionData = int(0)
    settings.bTryMeasurementMode = int(0)
    settings.bHasNivel = int(1)
    settings.bHasVideoCamera = int(1)
    command.SetSystemSettings(settings)
    set_status(status_label, 'Initialized')

def measure(command, rialg=None):
        CESAPI.refract.SetRefractionIndex(command, rialg)
        return command.StartMeasurement()

def calculate_transform(reflector_names,        cartesian_DSCS,\
                        target_reflector_names, initial_coordinates_LTCS):
    # extract the associated points from the configured DSCS reference network coordinates
    initial_coordinates_DSCS = numpy.ndarray((3, 3))
    for target_index,target_name in enumerate(target_reflector_names):
        logger.debug(reflector_names)
        logger.debug(target_name)
        logger.debug(reflector_names == target_name)
        initial_coordinates_DSCS[target_index,:] = cartesian_DSCS[reflector_names == target_name,:]
    logger.debug('Initial DSCS coordinates:\n{}'.format(initial_coordinates_DSCS))
    logger.debug('Initial LTCS coordinates:\n{}'.format(initial_coordinates_LTCS))

    # calculate the tracker position (S') in the DSCS to use as the fourth point
    A = initial_coordinates_LTCS[0]
    B = initial_coordinates_LTCS[1]
    C = initial_coordinates_LTCS[2]
    S = numpy.array([0, 0, 0])
    AB = B-A
    AC = C-A
    AS = -A
    z = numpy.cross(AB, AC)
    z_hat = z / linalg.norm(z)
    a = numpy.dot(z_hat, AS)
    b = numpy.dot(AB, AS)
    c = numpy.dot(AC, AS)
    
    Ap = initial_coordinates_DSCS[0]
    Bp = initial_coordinates_DSCS[1]
    Cp = initial_coordinates_DSCS[2]
    ABp = Bp-Ap
    ACp = Cp-Ap
    zp = numpy.cross(ABp, ACp)
    zp_hat = zp / linalg.norm(zp)
    M = numpy.vstack([zp_hat, ABp, ACp])
    M_inv = linalg.inv(M)
    ASp = numpy.dot(M_inv, numpy.array([a, b, c]))
    Sp = ASp + Ap
    logger.debug("S': {}".format(Sp))
    
    # calculate the DSCS-to-LTCS transform matrix
    X = numpy.vstack([[1, 1, 1, 1], numpy.vstack([A, B, C, S]).transpose()])
    Y = numpy.vstack([[1, 1, 1, 1], numpy.vstack([Ap, Bp, Cp, Sp]).transpose()])
    return numpy.dot(Y, linalg.pinv(X))

def scan_reference_network(command, ref_network_DSCS_filename_entry, reflector_name_selections, initial_measurements, labels, status_label=None):
    ref_network_DSCS_filename = ref_network_DSCS_filename_entry.get()
    reflector_names, cylindrical_DSCS, cartesian_DSCS = load_DSCS_coordinates(ref_network_DSCS_filename)

    initial_reflector_names = []
    for index,reflector_name_selection in enumerate(reflector_name_selections):
        reflector_name = reflector_name_selection.get()
        initial_reflector_names.append(reflector_name)
        logger.debug('Selected reflector {}: {}'.format(index, initial_reflector_names[index]))
    initial_reflector_names = numpy.array(initial_reflector_names)
    logger.debug('Initial reflector names: {}'.format(initial_reflector_names))
    if len(numpy.unique(initial_reflector_names)) != len(initial_reflector_names):
        raise Exception('One or more duplicates were found in the reflector selections.')

    for index,label in enumerate(labels):
        if label.cget('bg') != 'green':
            raise Exception('Initial reflector measurement {} was not performed.'.format(index))

    initial_cartesian_LTCS = numpy.ndarray((len(initial_measurements), 3))
    for point_index,initial_measurement in enumerate(initial_measurements):
        for coordinate_index,coordinate in enumerate(initial_measurement):
            initial_cartesian_LTCS[point_index, coordinate_index] = coordinate
    transform_matrix = calculate_transform(reflector_names,        cartesian_DSCS,\
                                           initial_reflector_names, initial_cartesian_LTCS)
    logger.debug('LTCS-to-DSCS Transform Matrix:\n{}'.format(transform_matrix))

    inv_transform_matrix = linalg.inv(transform_matrix)
    cartesian_LTCS = calculate_approx_LTCS(cartesian_DSCS, inv_transform_matrix)

    set_status(status_label, 'Setting coordinate system type to Counter-clockwise Spherical...')
    command.SetCoordinateSystemType(ES_CS_SCC)  # one of ES_CoordinateSystemType
    
    logger.debug('Cartesian LTCS:\n{}'.format(cartesian_LTCS))
    approx_spherical_LTCS = cartesian_to_spherical(cartesian_LTCS)
    logger.debug('Spherical LTCS:\n{}'.format(approx_spherical_LTCS))

    set_status(status_label, 'Ref. network 2-face measurements...')
    measurements_face1 = numpy.ndarray((numpy.shape(cartesian_LTCS)[0], 9))
    measurements_face2 = numpy.ndarray((numpy.shape(cartesian_LTCS)[0], 9))
    for index,spherical_point in enumerate(approx_spherical_LTCS):
        logger.debug('Directing laser to coordinates {}...'.format(spherical_point))
        command.GoPosition(int(1), spherical_point[0], spherical_point[1], spherical_point[2])

        # the tracker always switches to face 1 after a GoPosition command
        measurements_face1[index] = measurement_to_array(measure(command))

        # the tracker always switches to face 1 after a GoPosition command
        command.ChangeFace()
        measurements_face2[index] = measurement_to_array(measure(command))
    logger.debug('Face 1 Measurements:\n{}'.format(measurements_face1))
    logger.debug('Face 2 Measurements:\n{}'.format(measurements_face2))

    # calculate the average coordinates from the two-face measurements
    spherical_LTCS = numpy.ndarray((numpy.shape(cartesian_LTCS)))
    for index in range(numpy.shape(measurements_face1)[0]):
        spherical_LTCS[index] = (measurements_face1[index,:3] + measurements_face2[index,:3]) / 2.0
    logger.debug('Spherical LTCS:\n{}'.format(spherical_LTCS))

    transform_filename, inv_transform_filename, ref_network_LTCS_filename \
        = generate_ref_data_filenames(ref_network_DSCS_filename)
    set_status(status_label, 'Saving data...')
    save_matrix(transform_filename, transform_matrix)
    logger.info('Saved the LTCS-to-DSCS transform matrix to\n{}'.format(transform_filename))
    save_matrix(inv_transform_filename, inv_transform_matrix)
    logger.info('Saved the DSCS-to-LTCS transform matrix to\n{}'.format(inv_transform_filename))
    save_coordinates(ref_network_LTCS_filename, reflector_names, spherical_LTCS)
    logger.info('Saved the spherical LTCS reference coordinates to\n{}'.format(ref_network_LTCS_filename))
    set_status(status_label, 'Ready...')

def scan_other_network(command, ref_network_DSCS_filename_entry, network_DSCS_filename_entry, status_label=None):
    ref_network_DSCS_filename = ref_network_DSCS_filename_entry.get()
    reflector_names, cylindrical_DSCS, cartesian_DSCS = load_DSCS_coordinates(ref_network_DSCS_filename)

    network_LTCS_filename, reflector_names, approx_spherical_LTCS = convert_network_to_LTCS(ref_network_DSCS_filename_entry, network_DSCS_filename_entry, status_label=None)

    set_status(status_label, 'Setting coordinate system type to Counter-clockwise Spherical...')
    command.SetCoordinateSystemType(ES_CS_SCC)  # one of ES_CoordinateSystemType

    measurements_face1 = numpy.ndarray((numpy.shape(approx_spherical_LTCS)[0], 9))
    for index,spherical_point in enumerate(approx_spherical_LTCS):
        logger.debug('Directing laser to coordinates {}...'.format(spherical_point))
        command.GoPosition(int(1), spherical_point[0], spherical_point[1], spherical_point[2])

        # the tracker always switches to face 1 after a GoPosition command
        measurements_face1[index] = measurement_to_array(measure(command))
    logger.debug('Face 1 Measurements:\n{}'.format(measurements_face1))

    # calculate the average coordinates from the two-face measurements
    spherical_LTCS = numpy.ndarray((numpy.shape(approx_spherical_LTCS)))
    for index in range(numpy.shape(measurements_face1)[0]):
        spherical_LTCS[index] = measurements_face1[index,:3]
    logger.debug('Spherical LTCS:\n{}'.format(spherical_LTCS))

    save_coordinates(network_LTCS_filename, reflector_names, spherical_LTCS)
    logger.info('Saved the spherical LTCS coordinates to\n{}'.format(network_LTCS_filename))
    set_status(status_label, 'Saved data.')

def convert_network_to_LTCS(ref_network_DSCS_filename_entry, network_DSCS_filename_entry, status_label=None):
    ref_network_DSCS_filename = ref_network_DSCS_filename_entry.get()
    _, transform_filename, _  = generate_ref_data_filenames(ref_network_DSCS_filename)

    network_DSCS_filename = network_DSCS_filename_entry.get()
    reflector_names, _, cartesian_DSCS = load_DSCS_coordinates(network_DSCS_filename)

    transform_matrix = load_matrix(transform_filename)

    # apply the DSCS-to-LTCS transform matrix
    X = numpy.vstack([numpy.ones(numpy.shape(cartesian_DSCS)[0]), cartesian_DSCS.transpose()])
    cartesian_LTCS = numpy.dot(transform_matrix, X)[1:,:].transpose()
    
    # convert to spherical LTCS
    spherical_LTCS = numpy.ndarray(numpy.shape(cartesian_LTCS))
    for index,cartesian_point in enumerate(cartesian_LTCS):
        spherical_LTCS[index,2] = math.sqrt(numpy.sum(cartesian_point**2))
        spherical_LTCS[index,0] = math.atan2(cartesian_point[1], cartesian_point[0])
        spherical_LTCS[index,1] = math.acos(cartesian_point[2]/spherical_LTCS[index,2])

    # save spherical LTCS coordinates
    network_LTCS_filename = generate_data_filename(network_DSCS_filename)
    save_coordinates(network_LTCS_filename, reflector_names, spherical_LTCS)
    logger.info('Saved the spherical LTCS coordinates to\n{}'.format(network_LTCS_filename))
    set_status(status_label, 'Saved spherical LTCS coordinates')

    return (network_LTCS_filename, reflector_names, spherical_LTCS)

def convert_network_to_DSCS(ref_network_DSCS_filename_entry, network_DSCS_filename_entry, measurements, status_label=None):
    # load transform
    ref_network_DSCS_filename = ref_network_DSCS_filename_entry.get()
    transform_filename, _, _  = generate_ref_data_filenames(ref_network_DSCS_filename)
    transform = load_matrix(transform_filename)

    # convert measurements to cylindrical DSCS
    cartesian_LTCS = numpy.ndarray((len(measurements), 3))
    for point_index,measurement in enumerate(measurements):
        for coordinate_index,coordinate in enumerate(measurement):
            cartesian_LTCS[point_index, coordinate_index] = coordinate
    spherical_LTCS = cartesian_to_spherical(cartesian_LTCS)

    X = numpy.vstack([numpy.ones(numpy.shape(cartesian_LTCS)[0]), cartesian_LTCS.transpose()])
    cartesian_DSCS = numpy.dot(transform, X)[1:,:].transpose()
    logger.debug('Other Network Cartesian DSCS:\n{}'.format(cartesian_DSCS))
    cylindrical_DSCS = cartesian_to_cylindrical(cartesian_DSCS)

    # save DSCS and LTCS coordinates
    network_DSCS_filename = network_DSCS_filename_entry.get()
    network_LTCS_filename = generate_data_filename(network_DSCS_filename)
    save_coordinates(network_LTCS_filename, measurements.labels(), spherical_LTCS)
    logger.info('Saved the spherical LTCS coordinates to\n{}'.format(network_LTCS_filename))
    save_coordinates(network_DSCS_filename, measurements.labels(), cylindrical_DSCS)
    logger.info('Saved the cylindrical DSCS coordinates to\n{}'.format(network_DSCS_filename))
    set_status(status_label, 'Saved DSCS & LTCS coordinates')

def save_configuration(config_filename_entry, ref_DSCS_filename_entry, prop_DSCS_filename_entry, ds_DSCS_filename_entry, status_label=None):
    config_filename = config_filename_entry.get()
    with open(config_filename, 'w') as config_file:
        config_file.write('''
[position]
FindDelay = 0
MaxRetries = 1
SearchRadius = 200
''')

        ref_DSCS_filename = ref_DSCS_filename_entry.get()
        ref_DSCS_data = list(zip(*load_coordinates(ref_DSCS_filename)))
        ref_DSCS_names, ref_network_DSCS = list(zip(*sorted(ref_DSCS_data, key=lambda tup: tup[0])))
        logger.debug('ref_network_DSCS:\n{}'.format(ref_network_DSCS))
        transform_filename, inv_transform_filename, ref_LTCS_filename = generate_ref_data_filenames(ref_DSCS_filename)
        ref_LTCS_data = list(zip(*load_coordinates(ref_LTCS_filename)))
        ref_LTCS_names, ref_network_LTCS = list(zip(*sorted(ref_LTCS_data, key=lambda tup: tup[0])))
    
        prop_DSCS_filename = prop_DSCS_filename_entry.get()
        prop_DSCS_data = list(zip(*load_coordinates(prop_DSCS_filename)))
        prop_DSCS_names, prop_DSCS = list(zip(*sorted(prop_DSCS_data, key=lambda tup: tup[0])))
        prop_LTCS_filename = generate_data_filename(prop_DSCS_filename)
        prop_LTCS_data = list(zip(*load_coordinates(prop_LTCS_filename)))
        prop_LTCS_names, prop_network_LTCS = list(zip(*sorted(prop_LTCS_data, key=lambda tup: tup[0])))
    
        ds_DSCS_filename = ds_DSCS_filename_entry.get()
        ds_DSCS_data = list(zip(*load_coordinates(ds_DSCS_filename)))
        ds_DSCS_names, ds_DSCS = list(zip(*sorted(ds_DSCS_data, key=lambda tup: tup[0])))
        ds_LTCS_filename = generate_data_filename(ds_DSCS_filename)
        ds_LTCS_data = list(zip(*load_coordinates(ds_LTCS_filename)))
        ds_LTCS_names, ds_network_LTCS = list(zip(*sorted(ds_LTCS_data, key=lambda tup: tup[0])))

        config_file.write('\n# Set membership labels\n')
        config_file.write('SetMemberships = NULL\n')
        for name_index,name in enumerate(ref_DSCS_names):
            config_file.write('SetMemberships[{}] = "ref"\n'.format(name_index))
        for name_index,name in enumerate(prop_DSCS_names):
            config_file.write('SetMemberships[{}] = "prop"\n'.format(name_index))
        for name_index,name in enumerate(ds_DSCS_names):
            config_file.write('SetMemberships[{}] = "ds"\n'.format(name_index))
        next_index = len(ref_DSCS_names) + len(prop_DSCS_names) + len(ds_DSCS_names)
    
        config_file.write('\n# Predicted LTCS coordinate sets\n')
        config_file.write('PredictedLTCSCoordinateSets = NULL\n\n')
    
        config_file.write('# ref (approx. reference network coordinates)\n')
        for point_index,point in enumerate(ref_network_LTCS):
            config_file.write('# {}\n'.format(ref_LTCS_names[point_index]))
            for coordinate_index,coordinate in zip([1, 2, 0], point):
                if coordinate_index == 2:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.3f}\n'.format(point_index+next_index, coordinate_index, coordinate))
                else:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.6f}\n'.format(point_index+next_index, coordinate_index, coordinate))
        next_index += len(ref_DSCS_names)

        config_file.write('\n# prop (propeller reflectors in home position)\n')
        for point_index,point in enumerate(prop_network_LTCS):
            config_file.write('# {}\n'.format(prop_LTCS_names[point_index]))
            for coordinate_index,coordinate in zip([1, 2, 0], point):
                if coordinate_index == 2:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.3f}\n'.format(point_index+next_index, coordinate_index, coordinate))
                else:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.6f}\n'.format(point_index+next_index, coordinate_index, coordinate))
        next_index += len(prop_DSCS_names)
    
        config_file.write('\n# ds (detector solenoid reflectors)\n')
        for point_index,point in enumerate(ds_network_LTCS):
            config_file.write('# {}\n'.format(ds_LTCS_names[point_index]))
            for coordinate_index,coordinate in zip([1, 2, 0], point):
                if coordinate_index == 2:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.3f}\n'.format(point_index+next_index, coordinate_index, coordinate))
                else:
                    config_file.write('PredictedLTCSCoordinateSets[{},{}] = {:.6f}\n'.format(point_index+next_index, coordinate_index, coordinate))
    
        config_file.write('\n# Measured DSCS coordinate sets\n')
        config_file.write('MeasuredDSCSCoordinateSets = NULL\n')
    
        config_file.write('\n# ref\n')
        next_index = len(ref_DSCS_names) + len(prop_DSCS_names) + len(ds_DSCS_names)
        for point_index,point in enumerate(ref_network_DSCS):
            config_file.write('# {}\n'.format(ref_DSCS_names[point_index]))
            for coordinate_index,coordinate in zip([1, 2, 0], point):
                if coordinate_index == 2:
                    config_file.write('MeasuredDSCSCoordinateSets[{},{}] = {:.3f}\n'.format(point_index+next_index, coordinate_index, coordinate))
                else:
                    config_file.write('MeasuredDSCSCoordinateSets[{},{}] = {:.6f}\n'.format(point_index+next_index, coordinate_index, coordinate))
        next_index += len(ref_DSCS_names)

        config_file.write('\n# prop\n')
        for point_index,point in enumerate(prop_DSCS):
            config_file.write('# {}\n'.format(prop_DSCS_names[point_index]))
            for coordinate_index,coordinate in zip([0, 1, 2], point):
                config_file.write('MeasuredDSCSCoordinateSets[{},{}] = 0\n'.format(point_index+next_index, coordinate_index))
        next_index += len(prop_DSCS_names)

        config_file.write('\n# ds\n')
        for point_index,point in enumerate(ds_DSCS):
            config_file.write('# {}\n'.format(ds_LTCS_names[point_index]))
            for coordinate_index,coordinate in zip([0, 1, 2], point):
                config_file.write('MeasuredDSCSCoordinateSets[{},{}] = 0\n'.format(point_index+next_index, coordinate_index))
            

        config_file.write('\nUseConfiguredTransform = TRUE\n\n')
        config_file.write('# LTCS -> DSCS transform matrix\n')
        config_file.write('TransformMatrix = NULL\n')
    
        transform_matrix = load_matrix(transform_filename)
        for row_index,row in enumerate(transform_matrix):
            for element_index,element in enumerate(row):
                config_file.write('TransformMatrix[{},{}] = {:.6f}\n'.format(row_index, element_index, element))

def test():
    signal.signal(signal.SIGINT, signal_handler)

    ref_network_DSCS_filename, transform_filename, inv_transform_filename, ref_network_LTCS_filename \
        = generate_ref_data_filenames()

    reflector_names, cylindrical_DSCS, cartesian_DSCS = load_DSCS_coordinates(ref_network_DSCS_filename)

    target_reflector_names = ['ref#1', 'ref#2', 'ref#3']
    initial_coordinates_LTCS = numpy.array([[  2474.9726707,   -8535.6864827,   -5429.81259778],\
                                            [   125.91585051,   5615.60642652, -14967.48581864],\
                                            [   130.39720325,    273.51283084,    319.44138543]]).transpose()

    transform_matrix = calculate_transform(reflector_names,        cartesian_DSCS,\
                                           target_reflector_names, initial_coordinates_LTCS)
    logger.debug('DSCS-to-LTCS Transform Matrix:\n{}'.format(transform_matrix))

    spherical_LTCS = numpy.array([[  5.07929038e-02,   1.51822728e+00,   2.48166245e+03],
                                  [  2.35150483e+00,   1.56739118e+00,   4.16201919e+03],
                                  [  2.55967949e+00,   1.54402986e+00,   1.02209367e+04],
                                  [ -2.61766113e+00,   1.55445999e+00,   1.86843429e+04],
                                  [ -1.91881327e+00,   1.55073447e+00,   1.59251319e+04]])
    logger.info('Spherical LTCS:\n{}'.format(spherical_LTCS))

    save_matrix(transform_filename, transform_matrix)
    save_matrix(inv_transform_filename, inv_transform_matrix)
    save_coordinates(ref_network_LTCS_filename, reflector_names, spherical_LTCS)

def browse_csv_files(entry):
    csv_filename = tkfile.askopenfilename(filetype=(("CSV files", ".csv"),))
    entry.delete(0, tk.END)
    entry.insert(0, csv_filename)

def browse_ini_files(entry):
    csv_filename = tkfile.asksaveasfilename(filetype=(("CSV files", ".ini"),))
    entry.delete(0, tk.END)
    entry.insert(0, csv_filename)

def load_reflector_names(filename_entry, reflector_name_option_menus, reflector_name_selections):
    browse_csv_files(filename_entry)

    ref_network_DSCS_filename = filename_entry.get()
    reflector_names, _, _ = load_DSCS_coordinates(ref_network_DSCS_filename)

    next_reflector_index = int(0)
    for reflector_name_option_menu,reflector_name_selection in zip(reflector_name_option_menus, reflector_name_selections):
        reflector_name_options = reflector_name_option_menu.children['menu']
        reflector_name_options.delete(0, 'end')
        for reflector_name in reflector_names:
            reflector_name_selection.set(reflector_names[next_reflector_index])
            reflector_name_options.add_command(label=reflector_name, command=tk._setit(reflector_name_selection, reflector_name))
        next_reflector_index += 1

def build_reference_network_page(notebook, command):
    page = ttk.Frame(notebook)
    page.columnconfigure(0, minsize=100)
    page.columnconfigure(1, minsize=100)
    page.columnconfigure(2, minsize=100)
    page.columnconfigure(3, minsize=100)
    notebook.add(page, text="Reference Network")

    ordinals = ['1st', '2nd', '3rd']
    reflector_labels = []
    reflector_name_selections = []
    reflector_name_option_menus = []
    initial_measurements = MeasurementSet(command, 3, reflector_labels)
    for row in range(3):
        label = tk.Label(page, text='{} Reflector'.format(ordinals[row]), bg='red', fg='white')
        label.grid(row=row+1, stick='WE')
        reflector_labels.append(label)

        selection = tk.StringVar()
        reflector_name_selections.append(selection)
        option = tk.OptionMenu(page, selection, '')
        option.grid(row=row+1, column=1, columnspan=2, sticky='WE')
        reflector_name_option_menus.append(option)

        button = tk.Button(page, text="Measure", command=lambda index=row: initial_measurements.measure(index))
        button.grid(row=row+1, column=3, sticky='WE', pady=4)

    tk.Label(page, text='DSCS Data File').grid(row=0)
    ref_network_DSCS_filename_entry = tk.Entry(page)
    ref_network_DSCS_filename_entry.grid(row=0, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: load_reflector_names(ref_network_DSCS_filename_entry, reflector_name_option_menus, reflector_name_selections))
    button.grid(row=0, column=3, sticky='WE')

    tk.Label(page, text='Status').grid(row=7)
    status_label = tk.Label(page, text='Ready', bg='white', fg='blue')
    status_label.grid(row=7, column=1, columnspan=3, sticky='WE')

    tk.Button(page, text='Initialize', command=lambda: initialize(command, manualiof=False, status_label=status_label)).grid(row=4, column=1, sticky='WE', pady=4)
    tk.Button(page, text='Scan', command=lambda: scan_reference_network(command, ref_network_DSCS_filename_entry, reflector_name_selections, initial_measurements, reflector_labels, status_label=status_label)).grid(row=4, column=2, sticky='WE', pady=4)

    return ref_network_DSCS_filename_entry

def build_other_network_page(notebook, command, ref_network_DSCS_filename_entry):
    page = ttk.Frame(notebook)
    page.columnconfigure(0, minsize=100)
    page.columnconfigure(1, minsize=100)
    page.columnconfigure(2, minsize=100)
    page.columnconfigure(3, minsize=100)
    page.rowconfigure(1, minsize=30)
    page.rowconfigure(2, minsize=30)
    page.rowconfigure(3, minsize=30)
    notebook.add(page, text="Other Network")

    # data filename input
    tk.Label(page, text='DSCS Data File').grid(row=0)
    network_DSCS_filename_entry = tk.Entry(page)
    network_DSCS_filename_entry.grid(row=0, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: browse_csv_files(network_DSCS_filename_entry))
    button.grid(row=0, column=3, sticky='WE')
    
    # filler label
    tk.Label(page, text='').grid(row=1, stick='WE')

    # manual measurement control
    tk.Label(page, text='Name').grid(row=2)
    reflector_name_entry = tk.Entry(page)
    reflector_name_entry.grid(row=2, column=1, columnspan=2, sticky='WE')
    measurements = MeasurementSet(command, label_entry=reflector_name_entry)
    button = tk.Button(page, text='Measure', command=lambda: measurements.measure(append=True))
    button.grid(row=2, column=3, sticky='WE')
    
    # filler label
    tk.Label(page, text='').grid(row=3, stick='WE')
        

    tk.Label(page, text='Status').grid(row=7)
    status_label = tk.Label(page, text='Ready', bg='white', fg='blue')
    status_label.grid(row=7, column=1, columnspan=3, sticky='WE')

    tk.Button(page, text='DSCS to LTCS', command=lambda: convert_network_to_LTCS(ref_network_DSCS_filename_entry, network_DSCS_filename_entry, status_label=status_label)).grid(row=4, column=0, sticky='WE', pady=4)
    tk.Button(page, text='Initialize', command=lambda: initialize(command, manualiof=False, status_label=status_label)).grid(row=4, column=1, sticky='WE', pady=4)
    tk.Button(page, text='Scan', command=lambda: scan_other_network(command, ref_network_DSCS_filename_entry, network_DSCS_filename_entry, status_label=status_label)).grid(row=4, column=2, sticky='WE', pady=4)
    tk.Button(page, text='LTCS to DSCS', command=lambda: convert_network_to_DSCS(ref_network_DSCS_filename_entry, network_DSCS_filename_entry, measurements, status_label=status_label)).grid(row=4, column=3, sticky='WE', pady=4)
    return network_DSCS_filename_entry

def build_config_page(notebook, ref_network_DSCS_filename_entry, network_DSCS_filename_entry):
    page = ttk.Frame(notebook)
    page.columnconfigure(0, minsize=100)
    page.columnconfigure(1, minsize=100)
    page.columnconfigure(2, minsize=100)
    page.columnconfigure(3, minsize=100)
    page.rowconfigure(1, minsize=30)
    page.rowconfigure(2, minsize=30)
    page.rowconfigure(3, minsize=30)
    notebook.add(page, text="Configuration")

    # config filename input
    tk.Label(page, text='Config File').grid(row=0)
    config_filename_entry = tk.Entry(page)
    config_filename_entry.grid(row=0, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: browse_ini_files(config_filename_entry))
    button.grid(row=0, column=3, sticky='WE')

    # reference DSCS filename input
    tk.Label(page, text='Ref. DSCS File').grid(row=1)
    ref_DSCS_filename_entry = tk.Entry(page)
    ref_DSCS_filename_entry.grid(row=1, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: browse_csv_files(ref_DSCS_filename_entry))
    button.grid(row=1, column=3, sticky='WE')

    # propeller DSCS filename input
    tk.Label(page, text='Prop. DSCS File').grid(row=2)
    prop_DSCS_filename_entry = tk.Entry(page)
    prop_DSCS_filename_entry.grid(row=2, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: browse_csv_files(prop_DSCS_filename_entry))
    button.grid(row=2, column=3, sticky='WE')

    # detector DSCS solenoid filename input
    tk.Label(page, text='DS DSCS File').grid(row=3)
    ds_DSCS_filename_entry = tk.Entry(page)
    ds_DSCS_filename_entry.grid(row=3, column=1, columnspan=2, sticky='WE')
    button = tk.Button(page, text='Browse', command=lambda: browse_csv_files(ds_DSCS_filename_entry))
    button.grid(row=3, column=3, sticky='WE')

    tk.Label(page, text='Status').grid(row=7)
    status_label = tk.Label(page, text='Ready', bg='white', fg='blue')
    status_label.grid(row=7, column=1, columnspan=3, sticky='WE')

    tk.Button(page, text='Generate', command=lambda: save_configuration(config_filename_entry, ref_DSCS_filename_entry, prop_DSCS_filename_entry, ds_DSCS_filename_entry, status_label=status_label)).grid(row=4, column=1, columnspan=2, sticky='WE', pady=4)

def main():
    # signal.signal(signal.SIGINT, signal_handler)

    connection = CESAPI.connection.Connection()
    try:
        logger.info('Connecting to the laser tracker...')
        connection.connect()
        command = CESAPI.command.CommandSync(connection)
    except Exception as e:
        logger.error('Failed to connect to the laster tracker:\n{}'.format(e))
        connection.disconnect()

    root = tk.Tk()
    root.title('Bootstrap Position')

    notebook = ttk.Notebook(root)
    notebook.grid(row=0,column=1, rowspan=6, columnspan=3)

    ref_network_DSCS_filename_entry = build_reference_network_page(notebook, command)
    other_network_DSCS_filename_entry = build_other_network_page(notebook, command, ref_network_DSCS_filename_entry)
    build_config_page(notebook, ref_network_DSCS_filename_entry, other_network_DSCS_filename_entry)

    root.mainloop()
    
    connection.disconnect()

if __name__ == '__main__':
    main()
