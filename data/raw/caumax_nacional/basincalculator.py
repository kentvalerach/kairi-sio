"""
***************************************************************************
    basincalculator.py
    ---------------------
    Date       : Febrero-2025
    authors    : Victor Olaya (volayaf@gmail.com), servigis (jesusgarcia@servigis.com)
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""
import math
import statistics
from collections import defaultdict

from osgeo import gdal, ogr
from osgeo.gdalconst import *

import numpy as np

from qgis.core import QgsGeometry

from .layers import (
    I1ID,
    P0,
    getLayerPath,
    RAIN_2,
    RAIN_5,
    RAIN_10,
    RAIN_25,
    RAIN_100,
    RAIN_500,
    MDT,
    FLOWDIRS,
)


class BasinCalculator:
    def __init__(self):
        gdal.AllRegister()
        path = getLayerPath(MDT)
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
        band = dataset.GetRasterBand(1)
        self.nodataMdt = band.GetNoDataValue()
        self.mdt = band.ReadAsArray()
        self.geoTransform = dataset.GetGeoTransform()
        self.crs = dataset.GetProjection()
        self.cellsize = self.geoTransform[1]
        self.cellarea = self.cellsize * self.cellsize
        self.secondaryLayers = {}
        self.secondaryNodata = {}
        self.secondaryTransforms = {}

        self.xMaxDistance = None
        self.yMaxDistance = None

        path = getLayerPath(FLOWDIRS)
        dataset = gdal.Open(path, gdal.GA_ReadOnly)
        band = dataset.GetRasterBand(1)
        self.nodataDirs = band.GetNoDataValue()
        self.dirs = band.ReadAsArray()

        self.openLayer(getLayerPath(I1ID), I1ID)
        self.openLayer(getLayerPath(P0), P0)

        self.rainFiles = {
            2: RAIN_2,
            5: RAIN_5,
            10: RAIN_10,
            25: RAIN_25,
            100: RAIN_100,
            500: RAIN_500,
        }
        for returnPeriod, rainFile in self.rainFiles.items():
            path = getLayerPath(self.rainFiles[returnPeriod])
            self.openLayer(path, returnPeriod)

        self._resetValues()

    def openLayer(self, path, name):
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        band = ds.GetRasterBand(1)
        self.secondaryLayers[name] = band.ReadAsArray()
        self.secondaryTransforms[name] = ds.GetGeoTransform()
        self.secondaryNodata[name] = band.GetNoDataValue()

    def _resetValues(self):
        self.maxH = 0
        self.minH = 9000
        self.area = 0
        self.maxDistance = 0
        self.concentrationTime = 0

    def _mean(self, array):
        return statistics.mean([float(v) for v in array])

    def calculate(self, pt):
        self.pt = pt
        self._resetValues()
        self.basinCells = np.zeros(self.mdt.shape)
        self.p0Values = []
        self.i1idValues = []
        self.rainValues = defaultdict(list)
        x, y = gdal.ApplyGeoTransform(
            gdal.InvGeoTransform(self.geoTransform), pt.x(), pt.y()
        )
        x, y = int(x), int(y)

        self.minH = self.mdt[y, x]
        self._processCell(x, y)

        self.i1id = self._mean(self.i1idValues)
        self.p0 = self._mean(self.p0Values)
        self.rain = {k: self._mean(v) for k, v in self.rainValues.items()}

        self.concentrationTime = 0.3 * (
            math.pow(
                (self.maxDistance / 1000.0)
                / math.pow(((self.maxH - self.minH) / self.maxDistance), 0.25),
                0.76,
            )
        )

        self.computeBasinContour()

    def computeBasinContour(self):
        rows, cols = self.mdt.shape
        src_drv = gdal.GetDriverByName("MEM")
        src_ds = src_drv.Create("", cols, rows, 1)
        src_ds.SetGeoTransform(self.geoTransform)
        src_ds.SetProjection(self.crs)
        band = src_ds.GetRasterBand(1)
        band.WriteArray(self.basinCells)
        band.SetNoDataValue(0)

        dst_drv = ogr.GetDriverByName("Memory")
        dst_ds = dst_drv.CreateDataSource("basin")
        dst_layer = dst_ds.CreateLayer("", srs=None)
        gdal.Polygonize(band, None, dst_layer, -1, [], callback=None)

        self.basinGeometry = [
            QgsGeometry.fromWkt(f.GetGeometryRef().ExportToWkt()) for f in dst_layer
        ]

    def getValueAtCoordinate(self, x, y, layer):
        gt = self.secondaryTransforms[layer]
        px = int((x - gt[0]) / gt[1])
        py = int((y - gt[3]) / gt[5])
        val = self.secondaryLayers[layer][py, px]
        if val == self.secondaryNodata[layer]:
            return None
        else:
            return val

    directions = [
        (-1, 0, 1),
        (-1, -1, 2),
        (0, -1, 4),
        (1, -1, 8),
        (1, 0, 16),
        (1, 1, 32),
        (0, 1, 64),
        (-1, 1, 128),
    ]

    def _processCell(self, x, y, distance=0):
        coordx, coordy = gdal.ApplyGeoTransform(self.geoTransform, x + 0.5, y + 0.5)
        self.basinCells[y, x] = 1
        p0 = self.getValueAtCoordinate(coordx, coordy, P0)
        if p0 is not None and p0 > 0:
            self.p0Values.append(p0)
        i1id = self.getValueAtCoordinate(coordx, coordy, I1ID)
        if i1id is not None and i1id > 0:
            self.i1idValues.append(i1id)
        for returnPeriod in self.rainFiles.keys():
            rain = self.getValueAtCoordinate(coordx, coordy, returnPeriod)
            if rain is not None and rain > 0:
                self.rainValues[returnPeriod].append(rain)
        h = self.mdt[y, x]
        if distance > self.maxDistance or (
            distance == self.maxDistance and h < self.maxH
        ):
            self.maxDistance = distance
            self.maxH = h
            self.xMaxDistance, self.yMaxDistance = coordx, coordy
        self.area += self.cellarea
        for dx, dy, direction in self.directions:
            x2 = x + dx
            y2 = y + dy
            if self.dirs[y2, x2] == direction:
                distToNextCell = 1 if 0 in [dx, dy] else 1.414
                self._processCell(x2, y2, distance + distToNextCell * self.cellsize)
