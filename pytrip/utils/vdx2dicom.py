#!/usr/bin/env python
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
Script for converting Voxelplan / TRiP98 Vdx data to a DICOM file.
"""
import os
import sys
import logging
import argparse

import pytrip as pt

logger = logging.getLogger(__name__)


def main(args=sys.argv[1:]):
    """ Main function for vdx2dicom.py
    """
    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("vdx_data", help="location of VDX file (header or data) in TRiP98 format", type=str)
    parser.add_argument("outputdir", help="write resulting DICOM files to this directory", type=str)
    parser.add_argument("--ctx_data", help="location of CTX file (header or data) in TRiP98 format", type=str)
    parser.add_argument("-v", "--verbosity", action='count', help="increase output verbosity", default=0)
    parser.add_argument('-V', '--version', action='version', version=pt.__version__)
    parsed_args = parser.parse_args(args)

    if parsed_args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)
    elif parsed_args.verbosity > 1:
        logging.basicConfig(
            format='%(asctime)s,%(msecs)d _%(relativeCreated)d_ %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d:%H:%M:%S',
            level=logging.DEBUG
        )
    else:
        logging.basicConfig()

    output_dir = parsed_args.outputdir

    c = None
    if parsed_args.ctx_data:
        c = pt.CtxCube()
        try:
            c.read(parsed_args.ctx_data)
        except Exception as e:
            logger.error(e)
            return 1

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    logger.info("Convert VDX structures...")
    v = pt.VdxCube(cube=c)
    try:
        v.read(parsed_args.vdx_data)
    except Exception as e:
        logger.error(e)
        return 1
    v.write_dicom(output_dir)

    logger.info("Done")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))