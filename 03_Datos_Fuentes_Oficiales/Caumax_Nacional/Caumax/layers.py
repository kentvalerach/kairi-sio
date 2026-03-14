"""
***************************************************************************
    layers.py
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
import os
from functools import partial
from qgis.core import (
    QgsFeatureRequest,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsRectangle,
    QgsRaster,
    QgsProject,
    Qgis,
)
from qgis.gui import QgsMessageBar
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QFileDialog, QSizePolicy, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QIcon


IGNBASE = "BASE"
MDT = "MDT"
FLOWDIRS = "FLOWDIRS"
FLOW_2 = "FLOW_2"
FLOW_5 = "FLOW_5"
FLOW_10 = "FLOW_10"
FLOW_25 = "FLOW_25"
FLOW_100 = "FLOW_100"
FLOW_500 = "FLOW_500"
RAIN_2 = "RAIN_2"
RAIN_5 = "RAIN_5"
RAIN_10 = "RAIN_10"
RAIN_25 = "RAIN_25"
RAIN_100 = "RAIN_100"
RAIN_500 = "RAIN_500"
RIVERS = "RIVERS"
ZONES = "ZONES"
RIVER_NAME_FIELD = "corriente"
ORDINARY_PEAK_DISCHARGE_FIELD = "tmco"
ZONE_NAME_FIELD = "region"
ZONE_BETA = "betamedio"
ZONE_BETA50 = "IC50"
ZONE_BETA67 = "IC67"
ZONE_BETA90 = "IC90"
I1ID = "i1id"
P0 = "P0"
CP0T2 = "cp0t2"
CP0T5 = "cp0t5"
CP0T10 = "cp0t10"
CP0T25 = "cp0t25"
CP0T100 = "cp0t100"
CP0T500 = "cp0t500"
BASINS = "basins"
STATIONS = "stations"


def _fullPath(p):
    return os.path.join(os.path.dirname(__file__), "data", p)


_defaultLayerPaths = {
    RIVERS: _fullPath("rios.gpkg"),
    ZONES: _fullPath("regiones.gpkg"),
    FLOW_2: _fullPath("q2.tif"),
    FLOW_5: _fullPath("q5.tif"),
    FLOW_10: _fullPath("q10.tif"),
    FLOW_25: _fullPath("q25.tif"),
    FLOW_100: _fullPath("q100.tif"),
    FLOW_500: _fullPath("q500.tif"),
    RAIN_2: _fullPath("t2.tif"),
    RAIN_5: _fullPath("t5.tif"),
    RAIN_10: _fullPath("t10.tif"),
    RAIN_25: _fullPath("t25.tif"),
    RAIN_100: _fullPath("t100.tif"),
    RAIN_500: _fullPath("t500.tif"),
    MDT: _fullPath("mdt.tif"),
    FLOWDIRS: _fullPath("dir.tif"),
    I1ID: _fullPath("i1id.tif"),
    P0: _fullPath("p0.tif"),
    BASINS: _fullPath("demarcaciones_hidrograficas.gpkg"),
    STATIONS: _fullPath("Rear00ceh.gpkg"),
}

print("_defaultLayerPaths",_defaultLayerPaths)
_layerPaths = dict(_defaultLayerPaths)
print("_layerPaths",_layerPaths)

def loadLayerPathsFromSettings():
    layernames = [
        RAIN_2,
        RAIN_5,
        RAIN_10,
        RAIN_25,
        RAIN_100,
        RAIN_500,
        MDT,
        FLOWDIRS,
        P0,
    ]
    settings = QSettings()
    for name in layernames:
        v = settings.value(f"/caumax/{name}", None)
        print("valor v : ",v)
        if v is not None:
            _layerPaths[name] = v


loadLayerPathsFromSettings()

_layers = {}


def getLayer(name):
    if name == IGNBASE:
        return QgsRasterLayer(
            "crs=EPSG:25830&dpiMode=7&format=image/png&layers=mtn_rasterizado&styles&url=http://www.ign.es/wms-inspire/mapa-raster",
            "Mapa base IGN",
            "wms",
        )
    for layer in QgsProject.instance().mapLayers().values():
        if os.path.normpath(layer.source().split("|")[0]) == os.path.normpath(
            _layerPaths[name]
        ):
            print ("layer",layer)
            return layer
    if name not in _layers or (
        os.path.normpath(_layers[name].source()) != os.path.normpath(_layerPaths[name])
    ):
        layer = QgsRasterLayer(_layerPaths[name], name, "gdal")
        if not layer.isValid():
            layer = QgsVectorLayer(_layerPaths[name], name, "ogr")
        _layers[name] = layer

    return _layers[name]


def getLayerPath(layerid):
    return _layerPaths[layerid]


def getValueAtPoint(layerName, pt, field=None):
    layer = getLayer(layerName)
    if isinstance(layer, QgsRasterLayer):
        return list(
            layer.dataProvider()
            .identify(pt, QgsRaster.IdentifyFormatValue)
            .results()
            .values()
        )[0]
    else:
        searchRadius = 50
        r = QgsRectangle()
        r.setXMinimum(pt.x() - searchRadius)
        r.setXMaximum(pt.x() + searchRadius)
        r.setYMinimum(pt.y() - searchRadius)
        r.setYMaximum(pt.y() + searchRadius)

        feats = list(
            f
            for f in layer.getFeatures(
                QgsFeatureRequest()
                .setFilterRect(r)
                .setFlags(QgsFeatureRequest.ExactIntersect)
            )
        )
        if feats:
            return feats[0][field]


_riverNames = None


def riverNames():
    global _riverNames
    if _riverNames is None:
        _riverNames = []
        layer = getLayer(RIVERS)
        index = layer.fields().lookupField(RIVER_NAME_FIELD)
        request = (
            QgsFeatureRequest()
            .setSubsetOfAttributes([index])
            .setFlags(QgsFeatureRequest.NoGeometry)
        )
        for feature in layer.getFeatures(request):
            if feature[index] not in _riverNames:
                _riverNames.append(feature[index])
        _riverNames.sort()
    return _riverNames


WIDGET, BASE = uic.loadUiType(os.path.join(os.path.dirname(__file__), "layers.ui"))


def usesOnlyDefaultLayers():
    return _layerPaths == _defaultLayerPaths

def isOriginalFlowdirs():
    return _layerPaths.get('FLOWDIRS') == _defaultLayerPaths.get('FLOWDIRS')

def isLayerVisible(layer):
    print(layer.source())
    item = QgsProject.instance().layerTreeRoot().findLayer(layer)
    print(item)
    print(item.isVisible())
    if item:
        return item.isVisible()
    else:
        return False


class LayersDialog(BASE, WIDGET):
    def __init__(self):
        super(LayersDialog, self).__init__(iface.mainWindow())
        self.setupUi(self)

        iconpath = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        self.setWindowIcon(QIcon(iconpath))

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)

        self.buttonBox.accepted.connect(self.okPressed)
        self.buttonBox.rejected.connect(self.cancelPressed)
        self.btnDefault.clicked.connect(self.setDefaultPaths)

        self.layerbuttons = {
            RAIN_2: (self.btnRain2, self.comboRain2),
            RAIN_5: (self.btnRain5, self.comboRain5),
            RAIN_10: (self.btnRain10, self.comboRain10),
            RAIN_25: (self.btnRain25, self.comboRain25),
            RAIN_100: (self.btnRain100, self.comboRain100),
            RAIN_500: (self.btnRain500, self.comboRain500),
            MDT: (self.btnDEM, self.comboDEM),
            FLOWDIRS: (self.btnFlowDir, self.comboFlowDir),
            I1ID: (self.btnI1Id, self.comboI1Id),
            P0: (self.btnP0, self.comboP0),
        }

        for k in self.layerbuttons:
            btn, combo = self.layerbuttons[k]
            btn.clicked.connect(partial(self.btnFilenameClicked, combo))

        self.fillFilepaths()

        self.txtBasinSize.setText(str(QSettings().value("/caumax/basinsize", 10)))



    def setDefaultPaths(self):
        for k in self.layerbuttons:
            btn, combo = self.layerbuttons[k]
            self._setCurrentLayerFromPath(combo, _defaultLayerPaths[k])

        self.txtBasinSize.setText(str(10))
        print("_layerPaths ",_layerPaths, " _defaultLayerPaths ",_defaultLayerPaths)

    def _setCurrentLayerFromPath(self, combo, path):
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.source().split("|")[0] == path:
                combo.setLayer(layer)
                return
        additional = combo.additionalItems()
        additional.append(path)
        combo.setAdditionalItems(additional)
        combo.setCurrentText(path)

    def okPressed(self):
        MAX_CELLS = 10000
        settings = QSettings()
        try:
            area = float(self.txtBasinSize.text())
        except:
            self.bar.pushMessage(
                "", "Valor de área incorrecto", level=Qgis.Warning, duration=5
            )
            return
        if area < 1:
            self.bar.pushMessage(
                "",
                "No se permiten valores menores de 1",
                level=Qgis.Warning,
                duration=5,
            )
            return
        settings.setValue("/caumax/basinsize", area)

        layers = {}
        layerTooBig = False
        for k in self.layerbuttons:
            btn, combo = self.layerbuttons[k]
            layers[k] = combo.currentLayer()
            if layers[k] is None:
                layers[k] = QgsRasterLayer(combo.currentText(), "layer", "gdal")
                if not layers[k].isValid():
                    self.bar.pushMessage(
                        "",
                        f"Capa invalida ({os.path.basename(combo.currentText())})",
                        level=Qgis.Warning,
                        duration=5,
                    )
                    return
            if layers[k].width() > MAX_CELLS or layers[k].height() > MAX_CELLS:
                layerTooBig = True

        cellsizeDEM = layers[MDT].rasterUnitsPerPixelX()
        cellsizeFlowDir = layers[FLOWDIRS].rasterUnitsPerPixelX()
        if cellsizeDEM != cellsizeFlowDir:
            self.bar.pushMessage(
                "",
                "Las capas MDT y Direcciones de Flujo deben tener el mismo tamaño de celda",
                level=Qgis.Warning,
                duration=5,
            )
            return

        for k in self.layerbuttons:
            btn, combo = self.layerbuttons[k]
            _layerPaths[k] = layers[k].source()
            settings.setValue(f"/caumax/{k}", _layerPaths[k])
        self.close()

    def cancelPressed(self):
        self.close()

    def btnFilenameClicked(self, combo):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar fichero de capa", ""
        )
        if filename:
            additional = combo.additionalItems()
            additional.append(filename)
            combo.setAdditionalItems(additional)
            combo.setCurrentText(filename)

    def fillFilepaths(self):
        for k in self.layerbuttons:
            btn, combo = self.layerbuttons[k]
            self._setCurrentLayerFromPath(combo, _layerPaths[k])
