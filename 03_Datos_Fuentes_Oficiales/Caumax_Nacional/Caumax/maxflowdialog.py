"""
***************************************************************************
    maxflowdialog.py
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
from datetime import date
from qgis.PyQt import uic
from qgis.core import (
    QgsProject,
    QgsRectangle,
    QgsLayoutExporter,
    QgsPointXY,
    QgsPrintLayout,
    QgsReadWriteContext,
    Qgis,
    QgsUnitTypes,
    QgsLayoutSize,
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature,
)
from qgis.gui import QgsMessageBar, QgsVertexMarker
from qgis.utils import iface
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QSizePolicy, QFileDialog
from .layers import (
    getValueAtPoint,
    getLayer,
    riverNames,
    BASINS,
    IGNBASE,
    FLOW_2,
    FLOW_5,
    FLOW_10,
    FLOW_25,
    FLOW_100,
    FLOW_500,
    RIVERS,
    RIVER_NAME_FIELD,
    ZONES,
    ZONE_NAME_FIELD,
    STATIONS,
    isLayerVisible,
)
from .pointmaptool import PointMapTool
from qgis.PyQt.QtWidgets import (
    QSizePolicy,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
)

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "maxflowdialog.ui")
)


class MaxFlowDialog(BASE, WIDGET):
    def __init__(self):
        super(MaxFlowDialog, self).__init__(iface.mainWindow())
        self.setupUi(self)
        iconpath = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        self.setWindowIcon(QIcon(iconpath))

        self.buttonsAndLayers = {
            self.radioReturnPeriod2: FLOW_2,
            self.radioReturnPeriod5: FLOW_5,
            self.radioReturnPeriod10: FLOW_10,
            self.radioReturnPeriod25: FLOW_25,
            self.radioReturnPeriod100: FLOW_100,
            self.radioReturnPeriod500: FLOW_500,
        }
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)

        self.btnZoomToRiverName.clicked.connect(self.zoomToRiverName)

        canvas = iface.mapCanvas()
        self.prevMapTool = canvas.mapTool()

        self.tool = PointMapTool(canvas)
        self.tool.canvasClicked.connect(self.updatePoint)
        self.btnGetPoint.clicked.connect(self.getPointClicked)

        self.btnCalculate.clicked.connect(self.calculate)
        self.btnClose.clicked.connect(self.close)
        self.btnReport.clicked.connect(self.createReport)

        self.txtX.textChanged.connect(lambda: self.btnReport.setEnabled(False))
        self.txtY.textChanged.connect(lambda: self.btnReport.setEnabled(False))
        for btn in self.buttonsAndLayers.keys():
            btn.toggled.connect(lambda: self.btnReport.setEnabled(False))

        self.btnReport.setEnabled(False)

        self.populateRivers()

        self.marker = None

    def populateRivers(self):
        self.comboRiverName.addItems(riverNames())

    def zoomToRiverName(self):
        name = self.comboRiverName.currentText()
        layer = getLayer(RIVERS)
        layer.selectByExpression("\"%s\" = '%s'" % (RIVER_NAME_FIELD, name))
        box = layer.boundingBoxOfSelected()
        iface.mapCanvas().setExtent(box)
        iface.mapCanvas().refresh()

    def calculate(self):
        try:
            x = float(self.txtX.text())
            y = float(self.txtY.text())
        except:
            QMessageBox.warning(
                self,
                "Error de localización",
                "Las coordenadas introducidas no son válidas",
            )

            return

        for btn in self.buttonsAndLayers.keys():
            if btn.isChecked():
                returnPeriod = btn

        pt = QgsPointXY(x, y)

        if self.marker is None:
            self.marker = QgsVertexMarker(iface.mapCanvas())
        self.marker.setCenter(pt)
        self.marker.setIconSize(8)
        self.marker.setPenWidth(4)

        v = getValueAtPoint(self.buttonsAndLayers[returnPeriod], pt)
        zone = getValueAtPoint(ZONES, pt, ZONE_NAME_FIELD)
		
        if zone is None:
            QMessageBox.warning(
                self,
                "Error de localización",
                "Se ha seleccionado un punto fuera de la cuenca.",
            )
            return
        if v is None:
            QMessageBox.warning(
                self,
                "Error de localización",
                "No existe información para ese punto en el Mapa de Caudales Máximos. Puede recurrir a las  "
                "herramientas del menú 'Método Racional' para realizar una estimación de los caudales en ese punto.\n",
            )

            self.btnReport.setEnabled(False)
        elif v == 99999:
            QMessageBox.warning(
                self,
                "Aviso",
                "No hay información disponible sobre caudales máximos en este punto "
                "por encontrarse los mismos en proceso de revisión.\n",
            )
            self.btnReport.setEnabled(False)
        else:
            self.txtResultReturnPeriod.setText(returnPeriod.text())
            if zone == 33:
                self.txtResultFlow.setText("%.1f" % v)
            else:
                self.txtResultFlow.setText("%.0f" % v)
            self.lastValidPoint = pt
            self.btnReport.setEnabled(True)

    def getPointClicked(self):
        if self.btnGetPoint.isChecked():
            canvas = iface.mapCanvas()
            canvas.setMapTool(self.tool)
        else:
            canvas = iface.mapCanvas()
            canvas.setMapTool(self.prevMapTool)

    def updatePoint(self, point, button):
        self.txtX.setText("%.1f" % (point.x()))
        self.txtY.setText("%.1f" % (point.y()))
        if self.marker is None:
            self.marker = QgsVertexMarker(iface.mapCanvas())
        self.marker.setCenter(point)
        self.marker.setIconSize(8)
        self.marker.setPenWidth(4)
        self.calculate()

    def createReport(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Informe", "", "Archivos PDF (*.pdf)"
        )
        if not filename:
            return
        templateFilename = os.path.join(
            os.path.dirname(__file__), "templates", "maxflow.qpt"
        )
        document = QDomDocument()
        with open(templateFilename) as f:
            document.setContent(f.read())
        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.loadFromTemplate(document, QgsReadWriteContext())

        zone = getValueAtPoint(BASINS, self.lastValidPoint, field="DEMAR")
        title = layout.itemById("title")
        title.setText(f"Demarcación Hidrográfica del {zone.title()}")

        flow = self.txtResultFlow.text()
        returnPeriod = self.txtResultReturnPeriod.text()
        label = layout.itemById("coords")
        label.setText(
            f"X utm: {self.lastValidPoint.x()} - Y utm: {self.lastValidPoint.y()}"
        )
        label = layout.itemById("result")
        label.setText(
            f"Periodo de retorno (años): {returnPeriod}  -  Caudal (m³/s): {flow}"
        )
        label = layout.itemById("date")
        label.setText("Fecha: " + str(date.today().strftime("%d/%m/%Y")))

        bufferDist = 10000
        r = QgsRectangle(self.lastValidPoint, self.lastValidPoint)
        r.grow(bufferDist)

        scale = layout.itemById("scale")
        scale.attemptResize(QgsLayoutSize(142, 13, QgsUnitTypes.LayoutMillimeters))

        pointlayer = QgsVectorLayer("Point?crs=epsg:23030", "Punto", "memory")
        prov = pointlayer.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(self.lastValidPoint))
        prov.addFeatures([feat])
        pointlayer.updateExtents()
        stylefile = os.path.join(os.path.dirname(__file__), "data", "point.qml")
        pointlayer.loadNamedStyle(stylefile)

        mainMap = layout.itemById("map")
        baselayer = getLayer(IGNBASE)
        baselayer.setName("Mapa base IGN")
        rivers = getLayer(RIVERS)
        rivers.setName("Ríos")
        basins = getLayer(BASINS)
        basins.setName("Demarcaciones")
        stations = getLayer(STATIONS)
        layers = [pointlayer, rivers, basins, baselayer]
        if isLayerVisible(stations):
            layers.insert(0, stations)
        mainMap.setLayers(layers)
        mainMap.setExtent(r)
        mainMap.attemptResize(QgsLayoutSize(202, 162, QgsUnitTypes.LayoutMillimeters))

        legend = layout.itemById("legend")
        root = legend.model().rootGroup()
        root.addLayer(pointlayer)
        root.addLayer(rivers)
        root.addLayer(basins)

        if isLayerVisible(stations):
            root.addLayer(stations)

        header = layout.itemById("header")
        header.setPicturePath(
            os.path.join(os.path.dirname(__file__), "templates", "cabecera.jpg")
        )

        exporter = QgsLayoutExporter(layout)
        exporter.exportToPdf(filename, QgsLayoutExporter.PdfExportSettings())
		
        self.bar.pushMessage(
            "", "Informe creado correctamente", level=Qgis.Success , duration=10
        )
		

    def closeEvent(self, evt):
        if self.marker is not None:
            iface.mapCanvas().scene().removeItem(self.marker)
            self.marker = None
        super().closeEvent(evt)
