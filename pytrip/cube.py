#
#    Copyright (C) 2010-2017 PyTRiP98 Developers.
#
#    This file is part of PyTRiP98.
#
#    PyTRiP98 is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    PyTRiP98 is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with PyTRiP98.  If not, see <http://www.gnu.org/licenses/>.
#
"""
This module provides the Cube class, which is used by the CTX, DOS, LET and VDX modules.
A cube is a 3D object holding data, such as CT Hounsfield units, Dose- or LET values.
"""
import copy
import json
import os
import re
import sys
import logging
import datetime
import pprint
from collections import OrderedDict, defaultdict
from enum import Enum, auto

import numpy as np

import pydicom
from pydicom import uid
from pydicom.datadict import dictionary_description, dictionary_keyword, keyword_for_tag, dictionary_VR, \
    dictionary_has_tag
from pydicom.dataset import Dataset, FileDataset
from pydicom.tag import Tag, BaseTag

from pytrip.error import InputError, FileNotFound
from pytrip.util import TRiP98FilePath, TRiP98FileLocator

logger = logging.getLogger(__name__)


class Cube(object):
    """ Top level class for 3-dimensional data cubes used by e.g. DosCube, CtxCube and LETCube.
    Otherwise, this cube class may be used for storing different kinds of data, such as number of cells,
    oxygenation level, surviving fraction, etc.
    """

    header_file_extension = '.hed'
    data_file_extension = None
    allowed_suffix = tuple()

    def __init__(self, cube=None):
        if cube is not None:  # copying constructor
            self.header_set = cube.header_set
            self.version = cube.version
            self.modality = cube.modality
            self.created_by = cube.created_by
            self.creation_info = cube.creation_info
            self.primary_view = cube.primary_view
            self.data_type = cube.data_type
            self.num_bytes = cube.num_bytes
            self.byte_order = cube.byte_order
            self.patient_name = cube.patient_name
            self.patient_id = cube.patient_id
            self.slice_dimension = cube.slice_dimension
            self.pixel_size = cube.pixel_size
            self.slice_distance = cube.slice_distance
            self.slice_thickness = cube.slice_thickness
            self.slice_number = cube.slice_number
            self.xoffset = cube.xoffset  # self.xoffset are in mm, synced with DICOM contours
            self.dimx = cube.dimx
            self.yoffset = cube.yoffset  # self.yoffset are in mm, synced with DICOM contours
            self.dimy = cube.dimy
            self.zoffset = cube.zoffset  # self.zoffset are in mm, synced with DICOM contours
            self.dimz = cube.dimz
            self.z_table = cube.z_table
            self.slice_pos = cube.slice_pos
            self.basename = cube.basename
            self._set_format_str()
            self._set_number_of_bytes()

            # here are included tags with _common_ values in case
            # data comes from DICOM directory with multiple tags (i.e. directory with CT scan data)
            self.common_meta_dicom_data = cube.common_meta_dicom_data
            self.common_dicom_data = cube.common_dicom_data


            # here are included tags with _specific_ values (different from file to file) in case
            # data comes from DICOM directory with multiple tags (i.e. directory with CT scan data)
            self.file_specific_dicom_data = cube.file_specific_dicom_data

            self.cube = np.zeros((self.dimz, self.dimy, self.dimx), dtype=cube.pydata_type)

        else:
            import getpass
            from pytrip import __version__ as _ptversion

            self.header_set = False
            self.version = "2.0"
            self.modality = "CT"
            self.created_by = getpass.getuser()
            self.creation_info = "Created with PyTRiP98 {:s}".format(_ptversion)
            self.primary_view = "transversal"  # e.g. transversal
            self.data_type = ""
            self.num_bytes = ""
            self.byte_order = "vms"  # aix or vms
            self.patient_name = ""
            self.patient_id = datetime.datetime.today().strftime('%Y%m%d-%H%M%S')  # create a new patient ID if absent
            self.slice_dimension = ""  # eg. 256 meaning 256x256 pixels.
            self.pixel_size = ""  # size in [mm]
            self.slice_distance = ""  # distance between slices in [mm]
            self.slice_thickness = ""  # thickness of slice (usually equal to slice_distance) in [mm]
            self.slice_number = ""  # number of slices in file.
            self.xoffset = 0.0
            self.dimx = ""  # number of pixels along x (e.g. 256)
            self.yoffset = 0.0
            self.dimy = ""
            self.zoffset = 0.0
            self.dimz = ""
            self.slice_pos = []
            self.basename = ""

            self.z_table = False  # positions are stored in self.slice_pos (list of slice#,pos(mm),thickness(mm),tilt)

            # here are included tags with _common_ values in case
            # data comes from DICOM directory with multiple tags (i.e. directory with CT scan data)
            self.common_meta_dicom_data = None
            self.common_dicom_data = None

            # here are included tags with _specific_ values (different from file to file) in case
            # data comes from DICOM directory with multiple tags (i.e. directory with CT scan data)
            self.file_specific_dicom_data = None

    def __add__(self, other):
        """ Overload + operator
        """
        c = type(self)(self)
        if Cube in other.__class__.__bases__:
            c.cube = other.cube + self.cube
        else:
            c.cube = self.cube + float(other)
        return c

    def __sub__(self, other):
        """ Overload - operator
        """
        c = type(self)(self)
        if Cube in other.__class__.__bases__:
            c.cube = self.cube - other.cube
        else:
            c.cube = self.cube - float(other)
        return c

    def __mul__(self, other):
        """ Overload * operator
        """
        c = type(self)(self)
        if Cube in other.__class__.__bases__:
            c.cube = other.cube * self.cube
        else:
            t = type(c.cube[0, 0, 0])
            c.cube = np.array(self.cube * float(other), dtype=t)
        return c

    def __div__(self, other):
        """ Overload / operator
        """
        c = type(self)(self)
        if Cube in other.__class__.__bases__:
            c.cube = self.cube / other.cube
        else:
            t = type(c.cube[0, 0, 0])
            c.cube = np.array(self.cube / float(other), dtype=t)
        c.cube[np.isnan(c.cube)] = 0  # fix division by zero NaNs
        return c

    __truediv__ = __div__

    # TODO __floordiv__ should also be handled

    def is_compatible(self, other):
        """ Check if this Cube object is compatible in size and dimensions with 'other' cube.

        A cube object can be a CtxCube, DosCube, LETCube or similar object.
        Unlike check_compatibility(), this function compares itself to the other cube.

        :param Cube other: The other Cube object which will be checked compatibility with.
        :returns: True if compatible.
        """
        return self.check_compatibility(self, other)

    @staticmethod
    def check_compatibility(a, b):
        """
        Simple comparison of cubes. if X,Y,Z dims are the same, and
        voxel sizes as well, then they are compatible. (Duck typed)

        See also the function is_compatible().

        :params Cube a: the first cube to be compared with the second (b).
        :params Cube b: the second cube to be compared with the first (a).

        """
        eps = 1e-5

        if a.dimx != b.dimx:
            return False
        elif a.dimy != b.dimy:
            return False
        elif a.dimz != b.dimz:
            return False
        elif (a.pixel_size - b.pixel_size) > eps:
            return False
        elif a.slice_distance != b.slice_distance:
            return False
        else:
            return True

    def indices_to_pos(self, indices):
        """ Translate index number of a voxel to real position in [mm], including any offsets.

        The z position is always following the slice positions.

        :params [int] indices: tuple or list of integer indices (i,j,k) or [i,j,k]
        :returns: list of positions, including offsets, as a list of floats [x,y,z]
        """
        pos = [(indices[0] + 0.5) * self.pixel_size + self.xoffset,
               (indices[1] + 0.5) * self.pixel_size + self.yoffset,
               self.slice_pos[indices[2]]]
        logger.debug("Map [i,j,k] {:d} {:d} {:d} to [x,y,z] {:.2f} {:.2f} {:.2f}".format(indices[0],
                                                                                         indices[1],
                                                                                         indices[2],
                                                                                         pos[0],
                                                                                         pos[1],
                                                                                         pos[2]))
        return pos

    def slice_to_z(self, slice_number):
        """ Return z-position in [mm] of slice number (starting at 1).

        :params int slice_number: slice number, starting at 1 and no bound check done here.
        :returns: position of slice in [mm] including offset
        """
        # note that self.slice_pos contains an array of positions including any zoffset.
        return self.slice_pos[slice_number - 1]

    def create_cube_from_equation(self, equation, center, limits, radial=True):
        """ Create Cube from a given equation.

        This function is currently out of order.

        """
        # TODO why eq not being used ?
        # eq = util.evaluator(equation)
        # TODO why data not being used ?
        # data = np.array(np.zeros((self.dimz, self.dimy, self.dimx)))
        x = np.linspace(0.5, self.dimx - 0.5, self.dimx) * self.pixel_size - center[0]
        y = np.linspace(self.dimx - 0.5, 0.5, self.dimx) * self.pixel_size - center[1]
        xv, yv = np.meshgrid(x, y)

    def mask_by_voi_all(self, voi, preset=0, data_type=np.int16):
        """ Attaches/overwrites Cube.data based on a given Voi.

        Voxels within the structure are filled it with 'preset' value.
        Voxels outside the contour will be filled with Zeros.

        :param Voi voi: the volume of interest
        :param int preset: value to be assigned to the voxels within the contour.
        :param data_type: numpy data type, default is np.int16

        TODO: this needs some faster implementation.
        """
        data = np.array(np.zeros((self.dimz, self.dimy, self.dimx)), dtype=data_type)
        if preset != 0:
            for i_z in range(self.dimz):
                for i_y in range(self.dimy):
                    # For a line along y, figure out how many contour intersections there are,
                    # then check how many intersections there are with x < than current point.
                    # If the number is odd, then the point is inside the VOI.
                    # If the number is even, then the point is outisde the VOI.
                    # This algorithm also works with multiple disconnected contours.
                    intersection = voi.get_row_intersections(self.indices_to_pos([0, i_y, i_z]))
                    if intersection is None:
                        break
                    if len(intersection) > 0:
                        k = 0
                        for i_x in range(self.dimx):
                            # count the number of intersections k along y, where intersection_x < current x position
                            if self.indices_to_pos([i_x, 0, 0])[0] > intersection[k]:
                                k += 1
                                if k >= len(intersection):
                                    break
                            if k % 2 == 1:  # voxel is inside structure, if odd number of intersections.
                                data[i_z][i_y][i_x] = preset
        self.cube = data

    def create_empty_cube(self, value, dimx, dimy, dimz, pixel_size, slice_distance, slice_offset=0.0):
        """ Creates an empty Cube object.

        Values are stored as 2-byte integers.

        :param int16 value: integer value which will be assigned to all voxels.
        :param int dimx: number of voxels along x
        :param int dimy: number of voxels along y
        :param int dimz: number of voxels along z
        :param float pixel_size: size of each pixel (x == y) in [mm]
        :param float slice_distance: the distance between two slices (z) in [mm]
        :param float slice_offset: start position of the first slice in [mm] (default 0.0 mm)
        """
        self.dimx = dimx
        self.dimy = dimy
        self.dimz = dimz
        self.slice_number = dimz
        self.pixel_size = pixel_size
        self.slice_distance = slice_distance
        self.slice_thickness = slice_distance  # use distance for thickness as default
        self.cube = np.ones((dimz, dimy, dimx), dtype=np.int16) * value
        self.slice_dimension = dimx
        self.num_bytes = 2
        self.data_type = "integer"
        self.pydata_type = np.int16
        self.slice_pos = [slice_distance * i + slice_offset for i in range(dimz)]
        self.header_set = True
        self.patient_id = ''

    def mask_by_voi(self, voi, value):
        """ Overwrites the Cube voxels within the given Voi with 'value'.

        Voxels within the structure are filled it with 'value'.
        Voxels outside the contour are not touched.

        :param Voi voi: the volume of interest
        :param value=0: value to be assigned to the voxels within the contour.
        """
        for i_z in range(self.dimz):
            for i_y in range(self.dimy):
                intersection = voi.get_row_intersections(self.indices_to_pos([0, i_y, i_z]))
                if intersection is None:
                    break
                if len(intersection) > 0:
                    k = 0
                    for i_x in range(self.dimx):
                        if self.indices_to_pos([i_x, 0, 0])[0] > intersection[k]:
                            k += 1
                            if k >= (len(intersection)):
                                break
                        if k % 2 == 1:  # voxel is inside structure, if odd number of intersections.
                            self.cube[i_z][i_y][i_x] = value

    def mask_by_voi_add(self, voi, value=0):
        """ Add 'value' to all voxels within the given Voi

        'value' is added to each voxel value within the given volume of interest.
        Voxels outside the volume of interest are not touched.

        :param Voi voi: the volume of interest
        :param value=0: value to be added to the voxel values within the contour.
        """
        for i_z in range(self.dimz):
            for i_y in range(self.dimy):
                intersection = voi.get_row_intersections(self.indices_to_pos([0, i_y, i_z]))
                if intersection is None:
                    break
                if len(intersection) > 0:
                    k = 0
                    for i_x in range(self.dimx):
                        if self.indices_to_pos([i_x, 0, 0])[0] > intersection[k]:
                            k += 1
                            if k >= (len(intersection)):
                                break
                        if k % 2 == 1:  # voxel is inside structure, if odd number of intersections.
                            self.cube[i_z][i_y][i_x] += value

    def merge(self, cube):
        self.cube = np.maximum(self.cube, cube.cube)

    def merge_zero(self, cube):
        self.cube[self.cube == 0] = cube.cube[self.cube == 0]

    # ######################  READING TRIP98 FILES #######################################

    @classmethod
    def header_file_name(cls, path_name):
        return TRiP98FilePath(path_name, cls).header

    @classmethod
    def data_file_name(cls, path_name):
        return TRiP98FilePath(path_name, cls).datafile

    def read(self, path):
        """
        Reads both TRiP98 data and its associated header into the Cube object.

        Cube can be read providing a filename stripped of extension, i.e:
        >>> import pytrip as pt
        >>> c1 = pt.CtxCube()
        >>> c1.read("tests/res/TST003/tst003000")

        We can also read header file and data path which do not share common basename:
        >>> c2 = pt.CtxCube()
        >>> c2.read(("tests/res/TST003/tst003012.hed", "tests/res/TST003/tst003000.ctx.gz"))

        :param path: string or sequence of strings (length 2)
        :return:
        """

        # let us check if path is a string in a way python 2 and 3 will like it
        # based on https://stackoverflow.com/questions/4843173/how-to-check-if-type-of-a-variable-is-string
        running_python2 = sys.version_info.major == 2
        path_string = isinstance(path, (str, bytes) if not running_python2 else basestring)  # NOQA: F821

        # single argument of string type, i.e. filename without extension
        if path_string:
            self.basename = os.path.basename(TRiP98FilePath(path, self).basename)

            path_locator = TRiP98FileLocator(path, self)

            header_path = path_locator.header
            datafile_path = path_locator.datafile

            if not datafile_path or not header_path:
                raise FileNotFound("Loading {:s} failed, file not found".format(path))

        # tuple with path to header and datafile
        elif len(path) == 2:
            header_path, datafile_path = path

            # security checks for header file
            # first check - validity of the path
            if not TRiP98FilePath(header_path, self).is_valid_header_path():
                logger.warning("Loading {:s} which doesn't look like valid header path".format(header_path))

            # second check - if file exists
            if not os.path.exists(header_path):
                header_path_locator = TRiP98FileLocator(header_path, self)
                if header_path_locator.header is not None:
                    logger.warning("Did you meant to load {:s}, instead of {:s} ?".format(header_path_locator.header,
                                                                                          header_path))
                raise FileNotFound("Loading {:s} failed, file not found".format(header_path))

            # security checks for datafile path
            # first check - validity of the path
            if not TRiP98FilePath(datafile_path, self).is_valid_datafile_path():
                logger.warning("Loading {:s} which doesn't look like valid datafile path".format(datafile_path))

            # second check - if file exists
            if not os.path.exists(datafile_path):
                datafile_path_locator = TRiP98FileLocator(datafile_path, self)
                if datafile_path_locator.datafile is not None:
                    logger.warning(
                        "Did you meant to load {:s}, instead of {:s} ?".format(datafile_path_locator.datafile,
                                                                               datafile_path))
                raise FileNotFound("Loading {:s} failed, file not found".format(datafile_path))

            self.basename = ""  # TODO user may provide two completely different filenames for header and datafile
            # i.e. read( ("1.hed", "2.dos"), what about basename then ?

        else:
            raise Exception("More than two arguments provided as path variable to Cube.read method")

        # finally read files
        self._read_trip_header_file(header_path=header_path)
        self._read_trip_data_file(datafile_path=datafile_path, header_path=header_path)

    def _read_trip_header_file(self, header_path):  # TODO: could be made private? #126
        """ Reads a header file, accepts also if file is .gz compressed.
        First the un-zipped files will be attempted to read.
        Should these not exist, then the .gz are attempted.

        However, if the .hed.gz file was explicitly stated,
        then this file will also be loaded, even if a .hed is available.
        """

        # sanity check
        if header_path is not None:
            logger.info("Reading header file" + header_path)
        else:
            raise IOError("Could not find file " + header_path)

        # load plain of gzipped file
        if header_path.endswith(".gz"):
            import gzip
            fp = gzip.open(header_path, "rt")
        else:
            fp = open(header_path, "rt")
        content = fp.read()
        fp.close()

        # fill self with data
        self._parse_trip_header(content)
        self._set_format_str()
        logger.debug("Format string:" + self.format_str)

    def _read_trip_data_file(self, datafile_path, header_path,
                             multiply_by_2=False):  # TODO: could be made private? #126
        """Read TRiP98 formatted data.

        If header file was not previously loaded, it will be attempted first.

        Due to an issue in VIRTUOS, sometimes DosCube data have been reduced with a factor of 2.
        Setting multiply_by_2 to True, will restore the true values, in this case.

        :param datafile_path: Path to TRiP formatted data.
        :param multiply_by_2: The data read will automatically be multiplied with a factor of 2.
        """

        # fill header data if self.header is empty
        if not self.header_set:
            self._read_trip_header_file(header_path)

        # raise exception if reading header failed
        if not self.header_set:
            raise InputError("Header file not loaded")

        # preparation
        data_dtype = np.dtype(self.format_str)
        data_count = self.dimx * self.dimy * self.dimz

        # load data from data file (gzipped or not)
        logger.info("Opening file: " + datafile_path)
        if datafile_path.endswith('.gz'):
            import gzip
            with gzip.open(datafile_path, "rb") as f:
                s = f.read(data_dtype.itemsize * data_count)
                tmpcube = np.frombuffer(s, dtype=data_dtype, count=data_count)
                # frombuffer returns read-only array, so we need to make it writable
                cube = np.require(tmpcube, dtype=data_dtype, requirements=['W', 'O'])
        else:
            cube = np.fromfile(datafile_path, dtype=data_dtype)

        if self.byte_order == "aix":
            logger.info("AIX big-endian data.")
            # byteswapping is not needed anymore, handled by "<" ">" in dtype

        # sanity check
        logger.info("Cube data points : {:d}".format(len(cube)))
        if len(cube) != self.dimx * self.dimy * self.dimz:
            logger.error("Header size and cube size dont match.")
            logger.error("Cube data points : {:d}".format(len(cube)))
            logger.error("Header says      : {:d} = {:d} * {:d} * {:d}".format(
                self.dimx * self.dimy * self.dimz,
                self.dimx,
                self.dimy,
                self.dimz))
            raise IOError("Header data and dose cube size are not consistent.")

        cube = np.reshape(cube, (self.dimz, self.dimy, self.dimx))
        if multiply_by_2:
            logger.warning("Cube was previously rescaled to 50%. Now multiplying with 2.")
            cube *= 2
        self.cube = cube

    def _parse_trip_header(self, content):
        """ Parses content which was read from a trip header.
        """
        i = 0
        self.header_set = True
        content = content.split('\n')
        self.z_table = False
        dicom_str = []
        # self.dicom_meta_common_str = ""
        # self.dicom_common_str = ""
        # self.dicom_specific_str = ""

        while i < len(content):
            if re.match("version", content[i]):
                self.version = content[i].split()[1]
            if re.match("modality", content[i]):
                self.modality = content[i].split()[1]
            if re.match("created_by", content[i]):
                self.created_by = content[i].replace("created_by ", "", 1)
                self.created_by = self.created_by.rstrip()
            if re.match("creation_info", content[i]):
                self.creation_info = content[i].replace("creation_info ", "", 1)
                self.creation_info = self.creation_info.rstrip()
            if re.match("primary_view", content[i]):
                self.primary_view = content[i].split()[1]
            if re.match("data_type", content[i]):
                self.data_type = content[i].split()[1]
            if re.match("num_bytes", content[i]):
                self.num_bytes = int(content[i].split()[1])
            if re.match("byte_order", content[i]):
                self.byte_order = content[i].split()[1]
            if re.match("patient_name", content[i]):
                self.patient_name = content[i].split()[1]
            if re.match("slice_dimension", content[i]):
                self.slice_dimension = int(content[i].split()[1])
            if re.match("pixel_size", content[i]):
                self.pixel_size = float(content[i].split()[1])
            if re.match("slice_distance", content[i]):
                self.slice_distance = float(content[i].split()[1])
                self.slice_thickness = float(content[i].split()[1])  # TRiP format only. See #342
            if re.match("slice_number", content[i]):
                self.slice_number = int(content[i].split()[1])
            if re.match("xoffset", content[i]):
                self.xoffset = int(content[i].split()[1])
            if re.match("yoffset", content[i]):
                self.yoffset = int(content[i].split()[1])
            if re.match("zoffset", content[i]):
                self.zoffset = int(content[i].split()[1])
            if re.match("dimx", content[i]):
                self.dimx = int(content[i].split()[1])
            if re.match("dimy", content[i]):
                self.dimy = int(content[i].split()[1])
            if re.match("dimz", content[i]):
                self.dimz = int(content[i].split()[1])
            if re.match("slice_no", content[i]):
                self.slice_pos = [float(j) for j in range(self.slice_number)]
                self.z_table = True
                i += 1
                for j in range(self.slice_number):
                    self.slice_pos[j] = float(content[i].split()[1])
                    i += 1
            # if re.match("#\*", content[i]):
            #     self.dicom_meta_common_str += content[i].lstrip("#*")
            if re.match("#@", content[i]):
                #self.dicom_common_str += content[i].lstrip("#@")
                dicom_str.append(content[i])
            # if re.match("#&", content[i]):
            #     self.dicom_specific_str += content[i].lstrip("#&")
            i += 1

        # zoffset from TRiP contains the integer amount of slice thicknesses as offset.
        # Here we convert to an actual offset in mm, which is stored in self
        self.xoffset *= self.pixel_size
        self.yoffset *= self.pixel_size
        self.zoffset *= self.slice_distance

        logger.debug("TRiP loaded offsets: {:f} {:f} {:f}".format(self.xoffset, self.yoffset, self.zoffset))

        # generate slice position tables, if absent in header file
        # Note:
        # - ztable in .hed is _without_ offset
        # - self.slice_pos however holds values _including_ offset.
        if not self.z_table:
            self.slice_pos = [self.zoffset + _i * self.slice_distance for _i in range(self.slice_number)]
        self._set_format_str()

        if dicom_str:
            if not hasattr(self, 'dicom_data'):
                self.dicom_data = AccompanyingDicomData()
            self.dicom_data.from_comment(dicom_str)

        # # read DICOM data from header file comments
        # if self.dicom_meta_common_str:
        #     tmp = self.dicom_meta_common_str.replace('\'', '\"')
        #     self.common_meta_dicom_data = pydicom.dataset.Dataset().from_json(tmp)
        # if self.dicom_common_str:
        #     tmp = self.dicom_common_str.replace('\'', '\"')
        #     self.common_dicom_data = pydicom.dataset.Dataset().from_json(tmp)
        # if self.dicom_specific_str:
        #     self.file_specific_dicom_data = {}
        #     tmp = self.dicom_specific_str.replace('\'', '\"')
        #     json_dataset = json.loads(tmp)
        #     for instance_id, ds in json_dataset.items():
        #         self.file_specific_dicom_data[int(instance_id)] = pydicom.dataset.Dataset().from_json(ds)

    def _set_format_str(self):
        """Set format string according to byte_order.
        """
        if self.byte_order == "vms":
            self.format_str = "<"
        elif self.byte_order == "aix":
            self.format_str = ">"
        self._set_number_of_bytes()

    def _set_number_of_bytes(self):
        """Set format_str and pydata_type according to num_bytes and data_type
        """
        if self.data_type == "integer":
            if self.num_bytes == 1:
                self.format_str += "b"
                self.pydata_type = np.int8
            if self.num_bytes == 2:
                self.format_str += "h"
                self.pydata_type = np.int16
            if self.num_bytes == 4:
                self.format_str += "i"
                self.pydata_type = np.int32
        elif self.data_type in ["float", "double"]:
            if self.num_bytes == 4:
                self.format_str += "f"
                self.pydata_type = np.float32
            if self.num_bytes == 8:
                self.format_str += "d"
                self.pydata_type = np.double
        else:
            print("Format:", self.byte_order, self.data_type, self.num_bytes)
            raise IOError("Unsupported format.")
        logger.debug("self.format_str: '{}'".format(self.format_str))

    # ######################  WRITING TRIP98 FILES #######################################

    def write(self, path):
        """Write the Cube and its header to a file with the filename 'path'.

        :param str path: path to header file, data file or basename (without extension)
        :returns: tuple header_path, datafile_path: paths to header file and datafiles where data was saved
        (may be different from input path if user provided a partial basename)
        """

        running_python2 = sys.version_info.major == 2
        path_string = isinstance(path, (str, bytes) if not running_python2 else basestring)  # NOQA: F821

        if path_string:
            header_path = self.header_file_name(path)
            datafile_path = self.data_file_name(path)

        elif len(path) == 2:
            header_path, datafile_path = path

            # security checks for header file
            # first check - validity of the path
            if not TRiP98FilePath(header_path, self).is_valid_header_path():
                logger.warning("Loading {:s} which doesn't look like valid header path".format(header_path))

            # security checks for datafile path
            # first check - validity of the path
            if not TRiP98FilePath(datafile_path, self).is_valid_datafile_path():
                logger.warning("Loading {:s} which doesn't look like valid datafile path".format(datafile_path))
        else:
            raise Exception("More than two arguments provided as path variable to Cube.read method")

        # finally write files
        self._write_trip_header(header_path)
        self._write_trip_data(datafile_path)

        return header_path, datafile_path

    def _write_trip_header(self, path):
        """ Write a TRiP98 formatted header file, based on the available meta data.

        :param path: fully qualified path, including file extension (.hed)
        """
        from distutils.version import LooseVersion
        output_str = "version " + self.version + "\n"
        output_str += "modality " + self.modality + "\n"
        # include created_by and creation_info only for files newer than 1.4
        if LooseVersion(self.version) >= LooseVersion("1.4"):
            output_str += "created_by {:s}\n".format(self.created_by)
            output_str += "creation_info {:s}\n".format(self.creation_info)
        output_str += "primary_view " + self.primary_view + "\n"
        output_str += "data_type " + self.data_type + "\n"
        output_str += "num_bytes " + str(self.num_bytes) + "\n"
        output_str += "byte_order " + self.byte_order + "\n"
        if self.patient_name == "":
            self.patient_name = "Anonymous"
        # patient_name in .hed must be equal to the base filename without extension, else TRiP98 wont import VDX
        _fname = os.path.basename(path)
        _pname = os.path.splitext(_fname)[0]
        output_str += "patient_name {:s}\n".format(_pname)
        output_str += "slice_dimension {:d}\n".format(self.slice_dimension)
        output_str += "pixel_size {:.7f}\n".format(self.pixel_size)
        output_str += "slice_distance {:.7f}\n".format(self.slice_distance)
        output_str += "slice_number " + str(self.slice_number) + "\n"
        output_str += "xoffset {:d}\n".format(int(round(self.xoffset / self.pixel_size)))
        output_str += "dimx {:d}\n".format(self.dimx)
        output_str += "yoffset {:d}\n".format(int(round(self.yoffset / self.pixel_size)))
        output_str += "dimy {:d}\n".format(self.dimy)

        # zoffset in Voxelplan .hed seems to be broken, and should not be used if not = 0
        # to apply zoffset, z_table should be used instead.
        # This means, self.zoffset should not be used anywhere.
        output_str += "zoffset 0\n"
        output_str += "dimz " + str(self.dimz) + "\n"
        if self.z_table:
            output_str += "z_table yes\n"
            output_str += "slice_no  position  thickness  gantry_tilt\n"
            for i, item in enumerate(self.slice_pos):
                output_str += "  {:<3d}{:14.4f}{:13.4f}{:14.4f}\n".format(i + 1, item,
                                                                          self.slice_thickness, 0)  # 0 gantry tilt
        else:
            output_str += "z_table no\n"

        # # add DICOM tags as a commented lines
        # if self.common_meta_dicom_data:
        #     common_dicom_dict = self.common_meta_dicom_data.to_json_dict()
        #     dicom_dict_to_save = {}
        #     for tag_name, tag_value in common_dicom_dict.items():
        #         # restring saving tags to a subset with reasonable values,
        #         # i.e. excluding big binary arrays with pixel data
        #         if 'Value' in tag_value.keys():
        #             dicom_dict_to_save[tag_name] = tag_value
        #     dicom_str = pprint.pformat(dicom_dict_to_save, width=180)
        #     output_str += "#############################################################\n"
        #     for line in dicom_str.splitlines():
        #         output_str += "#*" + line + "\n"
        #     output_str += "#############################################################\n"

        if self.dicom_data:
            output_str += self.dicom_data.to_comment()

        # add DICOM tags as a commented lines
        # if self.common_dicom_data:
        #     common_dicom_dict = self.common_dicom_data.to_json_dict()
        #     dicom_dict_to_save = {}
        #     for tag_name, tag_value in common_dicom_dict.items():
        #         # restring saving tags to a subset with reasonable values,
        #         # i.e. excluding big binary arrays with pixel data
        #         if 'Value' in tag_value.keys():
        #             dicom_dict_to_save[tag_name] = tag_value
        #     dicom_str = pprint.pformat(dicom_dict_to_save, width=180)
        #     output_str += "#############################################################\n"
        #     output_str += "####### This file was created from a DICOM data #############\n"
        #     output_str += "### Below JSON representation of _common_ DICOM tags   ######\n"
        #     output_str += "#############################################################\n"
        #     for line in dicom_str.splitlines():
        #         output_str += "#@" + line + "\n"
        #     output_str += "#############################################################\n"
        #     output_str += "######### End of text representation of DICOM tags ##########\n"
        #     output_str += "#############################################################\n"
        #
        # file_secific_dict_to_save = {}
        # for instance_no, ds in self.file_specific_dicom_data.items():
        #     common_dicom_dict = ds.to_json_dict()
        #     dicom_dict_to_save = {}
        #     for tag_name, tag_value in common_dicom_dict.items():
        #         # restring saving tags to a subset with reasonable values,
        #         # i.e. excluding big binary arrays with pixel data
        #         if 'Value' in tag_value.keys():
        #             dicom_dict_to_save[tag_name] = tag_value
        #     file_secific_dict_to_save[instance_no] = dicom_dict_to_save
        #
        # output_str += "#############################################################\n"
        # output_str += "### Below JSON representation of _specific_ DICOM tags   ######\n"
        # output_str += "#############################################################\n"
        # dicom_str = pprint.pformat(file_secific_dict_to_save, width=180)
        # for line in dicom_str.splitlines():
        #     output_str += "#&" + line + "\n"
        # output_str += "#############################################################\n"

        with open(path, "w+") as f:
            f.write(output_str)

    def _write_trip_data(self, path):
        """ Writes the binary data cube in TRiP98 format to a file.

        Type is specified by self.pydata_type and self.byte_order attributes.

        :param str path: Full path including file extension.
        """
        cube = np.array(self.cube, dtype=self.pydata_type)
        if self.byte_order == "aix":
            cube = cube.byteswap()
        cube.tofile(path)

    # ######################  READING DICOM FILES #######################################

    def _set_z_table_from_dicom(self, dcm):
        """ Creates the slice position lookup table based on a given Dicom object.
        The table is attached to self.

        :param DICOM dcm: DICOM object provided by pydicom.
        """
        # TODO: can we rely on that this will always be sorted?
        # if yes, then all references to whether this is sorted or not can be removed hereafter
        # (see also pytripgui) /NBassler
        self.slice_pos = []
        for i, dcm_image in enumerate(dcm["images"]):
            self.slice_pos.append(float(dcm_image.ImagePositionPatient[2]))

    def _set_header_from_dicom(self, dcm):
        """ Creates the header metadata for this Cube class, based on a given Dicom object.

        :param DICOM dcm: Dicom object which will be used for generating the header data.
        """
        first_file_ds = dcm["images"][0]

        # find common tags in header
        common_meta_tags = set(first_file_ds.file_meta.keys())
        for ds in dcm["images"][1:]:
            common_meta_tags.intersection_update(ds.file_meta.keys())

        # find tags with common values
        common_meta_tags_and_values = set()
        for tag in common_meta_tags:
            if all([first_file_ds.file_meta[tag] == current_file_ds.file_meta[tag] for current_file_ds in dcm["images"][1:]]):
                common_meta_tags_and_values.add(tag)

        # find common tags
        common_tags = set(first_file_ds.keys())
        for ds in dcm["images"][1:]:
            common_tags.intersection_update(ds.keys())

        # find tags with common values
        common_tags_and_values = set()
        for tag in common_tags:
            if all([first_file_ds[tag] == current_file_ds[tag] for current_file_ds in dcm["images"][1:]]):
                common_tags_and_values.add(tag)

        # find tags with specific value
        specific_tags = common_tags - common_tags_and_values

        # print("specific_tags, slice 1", specific_tags)
        # for tag in specific_tags:
        #     print(dcm["images"][1][tag])
        #
        # print("specific_tags, slice 2", specific_tags)
        # for tag in specific_tags:
        #     print(dcm["images"][2][tag])
        #
        self.version = "1.4"
        self.created_by = "pytrip"
        self.creation_info = "Created by PyTRiP98"
        self.primary_view = "transversal"
        self.dimz = len(dcm["images"])
        self.slice_number = self.dimz

        self.set_data_type(type(first_file_ds.pixel_array[0][0]))

        self.dicom_data = AccompanyingDicomData(
            ct_datasets=dcm.get("images"),
            structure_dataset=dcm.get("rtss"),
            dose_dataset=dcm.get("rtdose")
        )

        # check consistency of the files
        required_common_tags = set(Tag(name) for name in ['PatientName', 'PatientID', 'Rows', 'PixelSpacing',
                                                          'SliceThickness', 'Columns', 'StudyInstanceUID',
                                                          'SeriesInstanceUID'])
        if not required_common_tags.issubset(common_tags_and_values):
            problematic_tags = required_common_tags.difference(common_tags_and_values)
            for tag in problematic_tags:
                print("Not all files share the same tag '{:s}' and its value".format(dictionary_description(tag)))
            raise Exception("Not all files are compatible")

            # # here are included tags with _specific_ values (different from file to file) in case
            # # data comes from DICOM directory with multiple tags (i.e. directory with CT scan data)
            # self.file_specific_dicom_data = None

        self.common_dicom_data = Dataset()
        for tag_name in common_tags_and_values:
            self.common_dicom_data[tag_name] = first_file_ds[tag_name]

        self.common_meta_dicom_data = Dataset()
        for tag_name in common_meta_tags_and_values:
            self.common_meta_dicom_data[tag_name] = first_file_ds.file_meta[tag_name]

        self.file_specific_dicom_data = {}
        for ds in dcm["images"]:
            self.file_specific_dicom_data[ds.InstanceNumber] = Dataset()
            for tag_name in specific_tags:
                self.file_specific_dicom_data[ds.InstanceNumber][tag_name] = ds[tag_name]

        self.patient_name = first_file_ds.PatientName
        self.basename = first_file_ds.PatientID.replace(" ", "_")

        self.dimx = int(first_file_ds.Rows)  # (0028, 0010) Rows (US)
        self.slice_dimension = self.dimx

        self.dimy = int(first_file_ds.Columns)  # (0028, 0011) Columns (US)

        self.pixel_size = float(first_file_ds.PixelSpacing[0])  # (0028, 0030) Pixel Spacing (DS)

        self.slice_thickness = first_file_ds.SliceThickness  # (0018, 0050) Slice Thickness (DS)
        # slice_distance != SliceThickness. One may have overlapping slices. See #342

        self.xoffset = float(first_file_ds.ImagePositionPatient[0])
        self.yoffset = float(first_file_ds.ImagePositionPatient[1])
        self.zoffset = float(first_file_ds.ImagePositionPatient[2])  # note that zoffset should not be used.
        self._set_z_table_from_dicom(dcm)
        self.z_table = True

        # Fix for bug #342
        # TODO: slice_distance should probably be a list of distances,
        # but for now we will just use the distance between the first two slices.
        if len(self.slice_pos) > 1:  # _set_z_table_from_dicom() must be called before
            self.slice_distance = abs(self.slice_pos[1] - self.slice_pos[0])
            logger.debug("Slice distance set to {:.2f}".format(self.slice_distance))
        else:
            logger.warning("Only a single slice found. Setting slice_distance to slice_thickness.")
            self.slice_distance = self.slice_thickness

        if self.slice_thickness > self.slice_distance:
            # TODO: this is probably valid dicom format, however let's print a warning for now
            # as it may indicate some problem with the input dicom, as it is rather unusual.
            logger.warning("Overlapping slices found: slice thickness is larger than the slice distance.")

        self.set_byteorder()
        self.data_type = "integer"
        self.num_bytes = 2
        self._set_format_str()
        self.header_set = True

    def set_byteorder(self, endian=None):
        """Set/change the byte order of the data to be written to disk.

        Available options are:
        - 'little' vms, Intel style little-endian byte order.
        - 'big' aix, Motorola style big-endian byte order.
        - if unspecified, the native system dependent endianess is used.

        :param str endian: optional string containing the endianess.
        """
        if endian is None:
            endian = sys.byteorder
        if endian == 'little':
            self.byte_order = "vms"
        elif endian == 'big':
            self.byte_order = "aix"
        else:
            raise ValueError("set_byteorder error: unknown endian " + str(endian))

    def set_data_type(self, type):
        """ Sets the data type for the TRiP98 header files.

        :param numpy.type type: numpy type, e.g. np.uint16
        """
        if type is np.int8 or type is np.uint8:
            self.data_type = "integer"
            self.num_bytes = 1
        elif type is np.int16 or type is np.uint16:
            self.data_type = "integer"
            self.num_bytes = 2
        elif type is np.int32 or type is np.uint32:
            self.data_type = "integer"
            self.num_bytes = 4
        elif type is np.float:
            self.data_type = "float"
            self.num_bytes = 4
        elif type is np.double:
            self.data_type = "double"
            self.num_bytes = 8

    # ######################  WRITING DICOM FILES #######################################

    def create_dicom_base(self):
        if self.header_set is False:
            raise InputError("Header not loaded")

        # TODO tags + code datatypes are described here:
        # https://www.dabsoft.ch/dicom/6/6/#(0020,0012)
        # datatype codes are described here:
        # ftp://dicom.nema.org/medical/DICOM/2013/output/chtml/part05/sect_6.2.html

        meta = Dataset()
        meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
        meta.ImplementationClassUID = "1.2.3.4"
        meta.TransferSyntaxUID = uid.ImplicitVRLittleEndian  # Implicit VR Little Endian - Default Transfer Syntax
        ds = FileDataset("file", {}, file_meta=meta, preamble=b"\0" * 128)
        ds.PatientName = self.patient_name
        if self.patient_id in (None, ''):
            ds.PatientID = datetime.datetime.today().strftime('%Y%m%d-%H%M%S')
        else:
            ds.PatientID = self.patient_id  # Patient ID tag 0x0010,0x0020 (type LO - Long String)
        ds.PatientSex = 'O'  # Patient's Sex tag 0x0010,0x0040 (type CS - Code String)
        #                      Enumerated Values: M = male F = female O = other.
        ds.PatientBirthDate = '19010101'
        ds.SpecificCharacterSet = 'ISO_IR 100'
        ds.AccessionNumber = ''
        ds.is_little_endian = True
        ds.is_implicit_VR = True
        ds.SOPClassUID = '1.2.3'  # !!!!!!!!

        # Study Instance UID tag 0x0020,0x000D (type UI - Unique Identifier)
        ds.FrameofReferenceUID = '1.2.3'  # !!!!!!!!!
        ds.StudyDate = datetime.datetime.today().strftime('%Y%m%d')
        ds.StudyTime = datetime.datetime.today().strftime('%H%M%S')
        ds.PhotometricInterpretation = 'MONOCHROME2'
        ds.SamplesPerPixel = 1
        ds.ImageOrientationPatient = ['1', '0', '0', '0', '1', '0']
        ds.Rows = self.dimx
        ds.Columns = self.dimy
        ds.SliceThickness = str(self.slice_distance)
        ds.PixelSpacing = [self.pixel_size, self.pixel_size]

        # Add eclipse friendly IDs
        ds.StudyID = '1'  # Study ID tag 0x0020,0x0010 (type SH - Short String)
        ds.ReferringPhysiciansName = 'py^trip'  # Referring Physician's Name tag 0x0008,0x0090 (type PN - Person Name)
        ds.PositionReferenceIndicator = ''  # Position Reference Indicator tag 0x0020,0x1040
        ds.SeriesNumber = '1'  # SeriesNumber tag 0x0020,0x0011 (type IS - Integer String)

        return ds


class AccompanyingDicomData:

    class DataType(Enum):
        CT = auto()
        Dose = auto()
        Struct = auto()
        LET = auto()
        common_CT = auto()
        common_all = auto()

    def __init__(self, ct_datasets=[], dose_dataset=None, structure_dataset=None):
        logger.info("Creating Accompanying DICOM data")
        logger.debug("Accessing {:d} CT datasets".format(len(ct_datasets)))
        if dose_dataset:
            logger.debug("Accessing dose datasets")
        if structure_dataset:
            logger.debug("Accessing structure datasets")

        ######### save tag values
        self.headers_datasets = {}
        self.data_datasets = {}
        if dose_dataset:
            self.headers_datasets[self.DataType.Dose] = Dataset(copy.deepcopy(dose_dataset.file_meta))
            self.data_datasets[self.DataType.Dose] = Dataset(copy.deepcopy(dose_dataset))

            # remove Pixel Data to save space
            del self.data_datasets[self.DataType.Dose].PixelData

        if ct_datasets:
            self.headers_datasets[self.DataType.CT] = \
                dict((dataset.InstanceNumber, Dataset(copy.deepcopy(dataset.file_meta))) for dataset in ct_datasets)
            self.data_datasets[self.DataType.CT] = {}
            for dataset in ct_datasets:
                self.data_datasets[self.DataType.CT][dataset.InstanceNumber] = Dataset(copy.deepcopy(dataset))

                # remove Pixel Data to save space
                del self.data_datasets[self.DataType.CT][dataset.InstanceNumber].PixelData

        if structure_dataset:
            self.headers_datasets[self.DataType.Struct] = Dataset(copy.deepcopy(structure_dataset.file_meta))
            self.data_datasets[self.DataType.Struct] = Dataset(copy.deepcopy(structure_dataset))

            # remove Contour Data to save space
            for i, contour in enumerate(self.data_datasets[self.DataType.Struct].ROIContourSequence):
                for j, sequence in enumerate(contour.ContourSequence):
                    del self.data_datasets[self.DataType.Struct].ROIContourSequence[i].ContourSequence[j].ContourData

        self.update_common_tags_and_values()

    def update_common_tags_and_values(self):
        """
        TODO
        :return:
        """
        all_header_datasets = list(x for x in
                                   [*list(self.headers_datasets.get(self.DataType.CT, {}).values()),
                                    self.headers_datasets.get(self.DataType.Struct, None),
                                    self.headers_datasets.get(self.DataType.Dose, None)]
                                   if x)

        all_data_datasets = list(x for x in
                                 [*list(self.data_datasets.get(self.DataType.CT, {}).values()),
                                 self.data_datasets.get(self.DataType.Struct, None),
                                 self.data_datasets.get(self.DataType.Dose, None)]
                                 if x)

        # list of common tags+values for all datasets (header and data file)
        self.all_datasets_header_common = self.find_common_tags_and_values(all_header_datasets)
        self.all_datasets_data_common = self.find_common_tags_and_values(all_data_datasets)
        self.all_datasets_data_common.discard(Tag('PixelData'))

        # list of common tags+values for CT datasets (header and data file)
        self.ct_datasets_header_common = self.find_common_tags_and_values(
            list(self.headers_datasets.get(self.DataType.CT, {}).values()))
        self.ct_datasets_data_common = self.find_common_tags_and_values(
            list(self.headers_datasets.get(self.DataType.CT, {}).values())
        )
        self.ct_datasets_data_common.discard(Tag('PixelData'))

        # list of file specific tags (without values!) for CT datasets (header and data file)
        self.ct_datasets_header_specific = self.find_tags_with_specific_values(
            list(self.headers_datasets.get(self.DataType.CT, {}).values()))
        self.ct_datasets_data_specific = self.find_tags_with_specific_values(
            list(self.headers_datasets.get(self.DataType.CT, {}).values()))
        self.ct_datasets_data_specific.discard(Tag('PixelData'))


    @staticmethod
    def find_common_tags(list_of_datasets=[], access_method=lambda x: x):
        """
        TODO
        :param list_of_datasets:
        :param access_method:
        :return: set of common tags
        """
        common_tags = set()
        if list_of_datasets:
            common_tags = set(access_method(list_of_datasets[0]).keys())
            for dataset in list_of_datasets[1:]:
                common_tags.intersection_update(access_method(dataset).keys())
        return common_tags

    @classmethod
    def find_common_tags_and_values(cls, list_of_datasets=[], access_method=lambda x: x):
        """
        TODO
        :param list_of_datasets:
        :param access_method:
        :return: set of tuples (tag and values) with common values
        """
        common_tags_and_values = set()
        if list_of_datasets:
            common_tags = cls.find_common_tags(list_of_datasets, access_method)
            first_dataset = access_method(list_of_datasets[0])
            for tag in common_tags:
                if all([first_dataset[tag] == access_method(dataset)[tag] for dataset in list_of_datasets[1:]]):
                    common_tags_and_values.add((tag, first_dataset[tag].repval))
        return common_tags_and_values

    @classmethod
    def find_tags_with_specific_values(cls, list_of_datasets=[], access_method=lambda x: x):
        """
        TODO
        :param list_of_datasets:
        :param access_method:
        :return: set of common tags
        """
        tags_with_specific_values = set()
        if list_of_datasets:
            common_tags = cls.find_common_tags(list_of_datasets, access_method)
            first_dataset = access_method(list_of_datasets[0])
            for tag in common_tags:
                if not all([first_dataset[tag] == access_method(dataset)[tag] for dataset in list_of_datasets[1:]]):
                    tags_with_specific_values.add(tag)
        return tags_with_specific_values

    def to_comment(self):
        """

        :return:
        """

        self.update_common_tags_and_values()

        # generate data to save
        ct_json_dict = {}
        if self.DataType.CT in self.headers_datasets:
            ct_json_dict['header'] = {}
            first_instance_id = list(self.headers_datasets[self.DataType.CT].keys())[0]
            ct_json_dict['header']['common'] = Dataset(dict(
                (tag_name, self.headers_datasets[self.DataType.CT][first_instance_id][tag_name])
                for tag_name, _ in self.ct_datasets_header_common
            )).to_json_dict()

            ct_json_dict['header']['specific'] = {}
            for instance_id, dataset in  self.headers_datasets[self.DataType.CT].items():
                ct_json_dict['header']['specific'][instance_id] = \
                    Dataset(dict(
                        (tag_name, dataset[tag_name]) for tag_name in self.ct_datasets_header_specific
                    )).to_json_dict()

        if self.DataType.CT in self.data_datasets:
            ct_json_dict['data'] = {}
            first_instance_id = list(self.data_datasets[self.DataType.CT].keys())[0]
            ct_json_dict['data']['common'] = Dataset(dict(
                (tag_name, self.data_datasets[self.DataType.CT][first_instance_id][tag_name])
                for tag_name, _ in self.ct_datasets_data_common
            )).to_json_dict()

            ct_json_dict['data']['specific'] = {}
            for instance_id, dataset in  self.data_datasets[self.DataType.CT].items():
                ct_json_dict['data']['specific'][instance_id] = \
                    Dataset(dict(
                        (tag_name, dataset[tag_name]) for tag_name in self.ct_datasets_data_specific
                    )).to_json_dict()

        dose_json_dict = {}
        if self.DataType.Dose in self.headers_datasets:
            dose_json_dict['header'] = self.headers_datasets[self.DataType.Dose].to_json_dict()
        if self.DataType.Dose in self.data_datasets:
            dose_json_dict['data'] = self.data_datasets[self.DataType.Dose].to_json_dict()

        struct_json_dict = {}
        if self.DataType.Struct in self.headers_datasets:
            struct_json_dict['header'] = self.headers_datasets[self.DataType.Struct].to_json_dict()
        if self.DataType.Struct in self.data_datasets:
            struct_json_dict['data'] = self.data_datasets[self.DataType.Struct].to_json_dict()

        # save the result string
        result = ""
        if ct_json_dict or struct_json_dict or dose_json_dict:
            result += "#############################################################\n"
            result += "#############################################################\n"
            result += "####### This file was created from a DICOM data #############\n"
            result += "#############################################################\n"
            result += "#############################################################\n"

        if ct_json_dict:
            result += "####### CT begins #############\n"
            pretty_string = pprint.pformat(ct_json_dict, width=180)
            no_of_lines = len(pretty_string.splitlines())
            for line_no, line in enumerate(pretty_string.splitlines()):
                result += "#@CT@ line {:d} / {:d} : {:s}\n".format(line_no, no_of_lines, line)
            result += "####### CT ends #############\n"

        if struct_json_dict:
            result += "####### Struct begins #############\n"
            pretty_string = pprint.pformat(struct_json_dict, width=180)
            no_of_lines = len(pretty_string.splitlines())
            for line_no, line in enumerate(pretty_string.splitlines()):
                result += "#@Struct@ line {:d} / {:d} : {:s}\n".format(line_no, no_of_lines, line)
            result += "####### Struct ends #############\n"

        if dose_json_dict:
            result += "####### Dose begins #############\n"
            pretty_string = pprint.pformat(dose_json_dict, width=180)
            no_of_lines = len(pretty_string.splitlines())
            for line_no, line in enumerate(pretty_string.splitlines()):
                result += "#@Dose@ line {:d} / {:d} : {:s}\n".format(line_no, no_of_lines, line)
            result += "####### Dose ends #############\n"

        return result

    def from_comment(self, parsed_str):

        logger.debug("from_comment")
        re_exp = '#@(?P<type>.+)@ line (?P<line_no>.+) \/ (?P<line_total>.+) : (?P<content>.+)'
        regex = re.compile(re_exp)

        content_by_type = defaultdict(list)
        for i, line in enumerate(parsed_str):
            match = regex.search(line)
            if match:
                content_by_type[match.group('type')].append(match.group('content').replace('\'', '\"'))

        if 'CT' in content_by_type:
            ct_dicts = json.loads("\n".join(content_by_type['CT']))
            if ct_dicts['data']['specific']:
                self.data_datasets[self.DataType.CT] = {}
            for instance_id, dataset_dict in ct_dicts['data']['specific'].items():
                self.data_datasets[self.DataType.CT][instance_id] = Dataset().from_json(dataset_dict)
                self.data_datasets[self.DataType.CT][instance_id].update(
                    Dataset().from_json(ct_dicts['data']['common'])
                )

            if ct_dicts['header']['specific']:
                self.headers_datasets[self.DataType.CT] = {}
            for instance_id, dataset_dict in ct_dicts['header']['specific'].items():
                # instance_id : str
                self.headers_datasets[self.DataType.CT][instance_id] = Dataset().from_json(dataset_dict)
                self.headers_datasets[self.DataType.CT][instance_id].update(
                    Dataset().from_json(ct_dicts['header']['common'])
                )

        if 'Struct' in content_by_type:
            struct_dicts = json.loads("\n".join(content_by_type['Struct']))
            self.headers_datasets[self.DataType.Struct] = Dataset().from_json(struct_dicts['header'])
            self.data_datasets[self.DataType.Struct] = Dataset().from_json(struct_dicts['data'])

        if 'Dose' in content_by_type:
            dose_dicts = json.loads("\n".join(content_by_type['Dose']))
            self.headers_datasets[self.DataType.Dose] = Dataset().from_json(dose_dicts['header'])
            self.data_datasets[self.DataType.Dose] = Dataset().from_json(dose_dicts['data'])

        self.update_common_tags_and_values()


def __str__(self):

        def nice_tag_name(tag):
            if dictionary_has_tag(tag):
                return dictionary_keyword(tag_name)
            else:
                return ""

        result = "all datasets\n"
        result += "\theader (file meta) common tags and values:\n"
        for (tag_name, tag_value) in sorted(self.all_datasets_header_common, key=lambda x: x[0]):
            result += "\t\t{:s} {:s} = {:s}\n".format(str(tag_name), nice_tag_name(tag_name), str(tag_value))
        result += "\tdata common tags and values:\n"
        for (tag_name, tag_value) in sorted(self.all_datasets_data_common, key=lambda x: x[0]):
            result += "\t\t{:s} {:s} = {:s}\n".format(str(tag_name), nice_tag_name(tag_name), str(tag_value))

        result += "CT datasets\n"
        result += "\theader (file meta) common tags and values:\n"
        for (tag_name, tag_value) in sorted(self.ct_datasets_header_common, key=lambda x: x[0]):
            result += "\t\t{:s} {:s} = {:s}\n".format(str(tag_name), nice_tag_name(tag_name), str(tag_value))
        result += "\tdata common tags and values:\n"
        for (tag_name, tag_value) in sorted(self.ct_datasets_data_common, key=lambda x: x[0]):
            result += "\t\t{:s} {:s} = {:s}\n".format(str(tag_name), nice_tag_name(tag_name), str(tag_value))

        result += "CT datasets\n"
        result += "\theader (file meta) tags with specific values:\n"
        for tag_name in sorted(self.ct_datasets_header_specific):
            result += "\t\t{:s} {:s}\n".format(str(tag_name), nice_tag_name(tag_name))
        result += "\tdata tags with specific values:\n"
        for tag_name in sorted(self.ct_datasets_data_specific):
            result += "\t\t{:s} {:s}\n".format(str(tag_name), nice_tag_name(tag_name))

        return result
