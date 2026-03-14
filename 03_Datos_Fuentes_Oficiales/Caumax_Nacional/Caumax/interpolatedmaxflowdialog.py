"""
***************************************************************************
    interpolatedmaxflowdialog.py
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
import math
import sys
from datetime import date
import numpy as np
from scipy.optimize import fsolve

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
    ORDINARY_PEAK_DISCHARGE_FIELD,
    ZONES,
    ZONE_NAME_FIELD,
    isLayerVisible,
    STATIONS,
)
from .pointmaptool import PointMapTool
from .gui_utils import waitcursor

from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsPointXY,
    QgsPrintLayout,
    QgsUnitTypes,
    QgsLayoutSize,
    QgsLayoutExporter,
    QgsRectangle,
    QgsReadWriteContext,
    QgsGeometry,
    QgsFeature,
    QgsMessageOutput,
    Qgis,
)
from qgis.gui import QgsMessageBar, QgsVertexMarker
from qgis.utils import iface
from qgis.PyQt import uic
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIntValidator, QIcon
from qgis.PyQt.QtWidgets import (
    QSizePolicy,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
)

from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "interpolatedmaxflowdialog.ui")
)


class InterpolatedMaxFlowDialog(BASE, WIDGET):
    def __init__(self):
        super(InterpolatedMaxFlowDialog, self).__init__(iface.mainWindow())
        self.setupUi(self)

        iconpath = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        self.setWindowIcon(QIcon(iconpath))

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)

        self.btnZoomToRiverName.clicked.connect(self.zoomToRiverName)

        canvas = iface.mapCanvas()
        self.prevMapTool = canvas.mapTool()

        self.tool = PointMapTool(canvas)
        self.tool.canvasClicked.connect(self.updatePoint)
        self.tool.complete.connect(self.pointPicked)
        self.btnGetPoint.clicked.connect(self.getPoint)

        self.btnCalculate.clicked.connect(self._calculate)
        self.btnClose.clicked.connect(self.close)
        self.btnReport.clicked.connect(self.createReport)

        self.btnReport.setEnabled(False)
        self.btnFrequencyLaw.setEnabled(False)
        self.btnFitInfo.setEnabled(False)

        self.chkOrdinaryMaxFlood.stateChanged.connect(self.checkStateChanged)

        self.btnFrequencyLaw.clicked.connect(self.showFrequencyLaw)
        self.btnFitInfo.clicked.connect(self.showFitInfo)

        self.txtX.textChanged.connect(lambda: self.btnReport.setEnabled(False))
        self.txtY.textChanged.connect(lambda: self.btnReport.setEnabled(False))
        self.txtReturnPeriod.textChanged.connect(
            lambda: self.btnReport.setEnabled(False)
        )

        self.txtReturnPeriod.setValidator(QIntValidator(2, 500))

        self.populateRivers()

        self.marker = None

    def checkStateChanged(self, state):
        if state == Qt.Checked:
            self.txtReturnPeriod.setEnabled(False)
        else:
            self.txtReturnPeriod.setEnabled(True)
        self.btnReport.setEnabled(False)

    def populateRivers(self):
        self.comboRiverName.addItems(riverNames())

    def zoomToRiverName(self):
        name = self.comboRiverName.currentText()
        layer = getLayer(RIVERS)
        layer.selectByExpression("\"%s\" = '%s'" % (RIVER_NAME_FIELD, name))
        box = layer.boundingBoxOfSelected()
        iface.mapCanvas().setExtent(box)
        iface.mapCanvas().refresh()

    def returnPeriod(self):
        if self.chkOrdinaryMaxFlood.isChecked():
            pt = self.outletPoint()
            if pt is None:
                return None
            returnPeriod = getValueAtPoint(ZONES, pt, ORDINARY_PEAK_DISCHARGE_FIELD)
        else:
            try:
                returnPeriod = float(self.txtReturnPeriod.text())
            except:
                QMessageBox.warning(
                    self,
                    "Interpolación de cuantiles",
                    "Periodo de retorno inválido ",
                )
                return None
        return returnPeriod

    def outletPoint(self):
        try:
            x = float(self.txtX.text())
            y = float(self.txtY.text())
            return QgsPointXY(x, y)
        except:
            QMessageBox.warning(
                    self,
                    "Interpolación de cuantiles",
                    "Las coordenadas introducidas no son válidas.",
            )
            return

    def _calculate(self):
        self.calculate()

    @waitcursor
    def calculate(self):
        pt = self.outletPoint()

        if pt is None:
            print("valores pt = ",pt)
            return

        zone = getValueAtPoint(ZONES, pt, ZONE_NAME_FIELD)
        if zone is None:
            QMessageBox.warning(
                self,
                "Error de localización",
                "Se ha seleccionado un punto fuera de la cuenca.",
            )
            return



        returnPeriod = self.returnPeriod()
        if returnPeriod is None:
            return

        if self.chkOrdinaryMaxFlood.isChecked():
            QMessageBox.warning(
                self,
                "Aviso",
                "Los valores que proporciona esta aplicación para la máxima crecida ordinaria "
                "constituyen estimaciones basadas en asignar, mediante fórmulas aproximadas, "
                "un valor regional al periodo de retorno correspondiente a dicha crecida.\n\n"
                "Se trata, por tanto, de valores orientativos que no sustituyen a los valores "
                "obtenidos en los estudios concretos realizados para el deslinde del dominio "
                "público hidráulico.",
            )
            returnPeriod = getValueAtPoint(ZONES, pt, ORDINARY_PEAK_DISCHARGE_FIELD)
        else:
            try:
                returnPeriod = float(self.txtReturnPeriod.text())
                if returnPeriod < 2:
                    QMessageBox.warning(
                        self,
                        "Error de localización",
                        "No se puede asignar un periodo de retorno menos de 2 años.",
                    )
                    return
                if returnPeriod > 500:
                    QMessageBox.warning(
                        self,
                        "Error de localización",
                        "No se puede asignar un periodo de retorno mayor de 500 años.",
                    )
                    return

            except:
                QMessageBox.warning(
                    self,
                    "Interpolación de cuantiles",
                    "Valor incorrecto de periodo de retorno.",
                )

                return

        if self.marker is None:
            self.marker = QgsVertexMarker(iface.mapCanvas())
        self.marker.setCenter(pt)
        self.marker.setIconSize(8)
        self.marker.setPenWidth(4)

        q = [
            getValueAtPoint(lay, pt)
            for lay in [FLOW_2, FLOW_5, FLOW_10, FLOW_25, FLOW_100, FLOW_500]
        ]
        print("valores q = ",q)


        if None in q:
            QMessageBox.warning(
                self,
                "Error de localización",
                "No existe información para ese punto en el Mapa de Caudales Máximos. Puede recurrir a las  "
                "herramientas del menú 'Método Racional' para realizar una estimación de los caudales en ese punto.\n",
            )

        elif q[1] == 99999:
           QMessageBox.warning(
                self,
                "Aviso",
                "No hay información disponible sobre caudales máximos en este punto "
                "por encontrarse los mismos en proceso de revisión.\n",
           )
           self.btnReport.setEnabled(False)
        else:

            self.setFittedValues(q, zone)
            v = self._getFlow(returnPeriod)
            print ("valor v = ",v,"returnperiod = ",returnPeriod,"valor q = ", q)

            if self.chkOrdinaryMaxFlood.isChecked():
                self.txtResultReturnPeriod.setText("%.1f" % returnPeriod)
            else:
                self.txtResultReturnPeriod.setText("%.0f" % returnPeriod)

            if zone == 33:
                self.txtResultFlow.setText("%.1f" % v)
            else:
                if v > 1:
                    self.txtResultFlow.setText("%.0f" % v)
                else:
                    self.txtResultFlow.setText("%.2f" % v)
            self.lastValidPoint = pt
            self.btnReport.setEnabled(True)
            self.btnFitInfo.setEnabled(True)
            self.btnFrequencyLaw.setEnabled(True)

    def _getFlow(self, returnPeriod):
        prob = 1 - 1.0 / returnPeriod
        if self.useAlternativeFunction:

            def _f(val):
                try:
                    return (
                        math.exp(
                            (-self.alpha1 * math.exp(-val * self.lambda1))
                            - (self.alpha2 * math.exp(-val * self.lambda2))
                        )
                        - prob
                    )
                except:
                    return 1000

            return fsolve(_f, 75)[0]
        else:
            return self.mu + self.alpha / self.k * (
                1 - math.pow(-math.log(prob), self.k)
            )

    def _getmedian(self, returnPeriod):
            return -math.log(math.log(returnPeriod/(returnPeriod-1)))

    def _canvas(self):

        periods =  range(2,500)
        showperiods = [self._getmedian(x) for x in periods ]
        showkeyPeriods = [0.366513,1.499939987,2.250367327,3.198534261,4.600149227,6.213607264]
        values = [self._getFlow(x) for x in periods]
        keyPeriods = [2, 5, 10, 25, 100, 500]
        showkeyPeriods = [self._getmedian(x) for x in keyPeriods]
        keyValues = self.valuesForFitting
        canvas = FigureCanvas(Figure(figsize=(5, 3)))
        returnPeriod = float(self.txtResultReturnPeriod.text())
        flow = float(self.txtResultFlow.text())
        self._ax = canvas.figure.subplots()
        self._ax.set_xlabel("Periodo de retorno (años)")
        self._ax.set_ylabel("Caudal (m³/s)")
        self._ax.plot(showperiods, values)
        self._ax.plot(showkeyPeriods, keyValues, "ro")
        #print("flow ",flow, " flow_calculated ",self._getInterpolatedFlow(returnPeriod)," returnPeriodsForFitting[-1] ",self.returnPeriodsForFitting[-1])
        self._ax.plot(self._getmedian(returnPeriod), self._getFlow(returnPeriod), "go")
        self._ax.set_xticks(showkeyPeriods,minor=False)
        self._ax.set_xticklabels(['2','5','10','25','100','500'], minor=False)
        self._ax.grid()

        return canvas

    def showFrequencyLaw(self):
        canvas = self._canvas()
        imagePath = os.path.splitext("grafica.png")[0] + ".png"
        canvas.figure.savefig(imagePath, bbox_inches="tight")

        txt = (
            ""
        )
        img = os.path.join(
            os.path.dirname(__file__), "resources", "funcion_extremos.jpg"
        )
        txt += f"<p><img src={imagePath}></p>"

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.setText(txt)
        msg_box.setWindowTitle("Gráfico ley de frecuencia")
        msg_box.exec_()

    def showFitInfo(self):
        logo = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        if self.useAlternativeFunction:
            txt = (
                "Función de valores extremos de 2 componentes <br> Procedimiento de ajuste : mínimos cuadrados<br><br> alpha1: %.4f<br>alpha2: %.4f<br>lambda1: %.4f<br>lambda2: %.4f"
                % (self.alpha1, self.alpha2, self.lambda1, self.lambda2)
            )
            img = os.path.join(
                os.path.dirname(__file__), "resources", "funcion_tcev.jpg"
            )
        else:
            txt = (
                "Función de valores extremos generalizada <br> Procedimiento de ajuste : mínimos cuadrados<br><br> u: %.4f<br>alpha: %.4f<br>k: %.4f"
                % (self.mu, self.alpha, self.k)
            )
            img = os.path.join(
                os.path.dirname(__file__), "resources", "funcion_extremos.jpg"
            )

        txt += f"<p><img src={img}></p>"
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.setText(txt)
        msg_box.setWindowTitle("Información del ajuste")
        msg_box.exec_()

    def sqdif(self, qs, fs, a1, a2, lam1, lam2):
        difsum = 0
        Qini = 0
        fx0 = 1
        Fx0 = 0
        dDif_Q = 1
        for q, prob in zip(qs, fs):
            repeat = True
            Qini = q
            while repeat:
                Fx0 = math.exp(
                    (-a1 * math.exp(-Qini * lam1)) - (a2 * math.exp(-Qini * lam2))
                )
                fx0 = Fx0 - prob
                fx1 = (
                    (a1 * lam1 * math.exp(-Qini * lam1))
                    + (a2 * lam2 * math.exp(-Qini * lam2))
                ) * Fx0
                Qn = Qini - (fx0 / fx1)
                dDif_Q = Qn - Qini
                Qini = Qn
                repeat = fx0 > 0.00001 or dDif_Q > 0.001
            difsum += (Qini - q) * (Qini - q)
        return difsum

    def getSquaredDiff(self, alpha, mu, k, qs):
        diff = 0
        total = 0
        fs = [0.5, 0.8, 0.9, 0.96, 0.99, 0.998]
        for f, q in zip(fs, qs):
            v = mu + alpha / k * (1 - math.pow(-math.log(f), k))
            diff = v - q
            total += diff * diff

        return total

    def _range(self, start, end, step):
        while start < end:
            yield start
            start += step

    def gevCurveFit(self, qs):
        limit = (qs[1] + qs[4]) / 4
        interval = limit / 100
        minDiff = sys.float_info.max

        def frange(start, end, step):
            while start < end:
                yield start
                start += step

        alpha = 0
        mu = 0
        k = -0.5
        for testAlpha in frange(0, limit, interval):
            for testMu in frange(0, limit, interval):
                for testK in frange(-0.5, 0, 0.01):
                    diff = self.getSquaredDiff(testAlpha, testMu, testK, qs)
                    if diff < minDiff:
                        minDiff = diff
                        alpha = testAlpha
                        mu = testMu
                        k = testK

        return (alpha, mu, k)

    def tcevCurveFit(self, qs, fs):
        N = 10
        N2 = N * 2
        t1 = ((math.log(-math.log(0.5))) - (math.log(-math.log(0.9)))) / (qs[2] - qs[0])
        alpha1 = -(math.log(0.5)) / (math.exp((-qs[0] * t1)))

        t2 = ((math.log(-math.log(0.99))) - (math.log(-math.log(0.998)))) / (
            qs[5] - qs[4]
        )
        alpha2 = -(math.log(0.99)) / (math.exp((-qs[4] * t2)))

        minLam1 = t1 - (t1 * N) / 100
        maxLam1 = t1 + (t1 * N) / 100
        minA1 = alpha1 - (alpha1 * N) / 100
        maxA1 = alpha1 + (alpha1 * N) / 100

        minLam2 = t2 - (t2 * N) / 100
        maxLam2 = t2 + (t2 * N) / 100
        minA2 = alpha2 - (alpha2 * N) / 100
        maxA2 = alpha2 + (alpha2 * N) / 100

        minsqdif = None
        difA1 = (maxA1 - minA1) / N2
        difA2 = (maxA2 - minA2) / N2
        difLam1 = (maxLam1 - minLam1) / N2
        difLam2 = (maxLam2 - minLam2) / N2
        for n1 in range(N2):
            for n2 in range(N2):
                for n3 in range(N2):
                    for n4 in range(N2):
                        a1 = minA1 + n1 * difA1
                        a2 = minA2 + n2 * difA2
                        lam1 = minLam1 + n3 * difLam1
                        lam2 = minLam2 + n4 * difLam2
                        sqdif = self.sqdif(qs, fs, a1, a2, lam1, lam2)
                        if minsqdif is None or sqdif < minsqdif:
                            minsqdif = sqdif
                            fitted = [a1, a2, lam1, lam2]

        return fitted

    def setFittedValues(self, q, zone):
        self.valuesForFitting = q
        returnPeriods = [2, 5, 10, 25, 100, 500]
        if zone in [72, 73, 84, 821, 822]:
            self.useAlternativeFunction = True

            def _f(x, alpha1, alpha2, lambda1, lambda2):
                v = np.exp(
                    (-alpha1 * np.exp(-x * lambda1)) - (alpha2 * np.exp(-x * lambda2))
                )
                return v

            fs = [1 - 1.0 / r for r in returnPeriods]
            fitted = self.tcevCurveFit(q, fs)

            self.alpha1 = fitted[0]
            self.alpha2 = fitted[1]
            self.lambda1 = fitted[2]
            self.lambda2 = fitted[3]

        else:
            self.useAlternativeFunction = False
            gevfitted = self.gevCurveFit(q)
            self.alpha = gevfitted[0]
            self.mu = gevfitted[1]
            self.k = gevfitted[2]

    def getPoint(self):
        canvas = iface.mapCanvas()
        canvas.setMapTool(self.tool)
        self.showMinimized()

    def updatePoint(self, point, button):
        self.txtX.setText("%.1f" % point.x())
        self.txtY.setText("%.1f" % point.y())
        if self.marker is None:
            self.marker = QgsVertexMarker(iface.mapCanvas())
        self.marker.setCenter(point)
        self.marker.setIconSize(8)
        self.marker.setPenWidth(4)

    def pointPicked(self):
        canvas = iface.mapCanvas()
        canvas.setMapTool(self.prevMapTool)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def createReport(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Informe", "", "Archivos PDF (*.pdf)"
        )
        if not filename:
            return
        templateFilename = os.path.join(
            os.path.dirname(__file__), "templates", "interpolated.qpt"
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
            f"Periodo de retorno (años): {returnPeriod}"
        )
        label = layout.itemById("result2")
        label.setText(
            f"Caudal (m³/s): {flow}"
        )

        label = layout.itemById("date")
        label.setText("Fecha: " + str(date.today().strftime("%d/%m/%Y")))

        bufferDist = 10000
        r = QgsRectangle(self.lastValidPoint, self.lastValidPoint)
        r.grow(bufferDist)

        canvas = self._canvas()
        imagePath = os.path.splitext(filename)[0] + ".png"
        canvas.figure.savefig(imagePath, bbox_inches="tight",dpi=300)
        graph = layout.itemById("graph")
        graph.setPicturePath(imagePath)

        scale = layout.itemById("scale")
        scale.attemptResize(QgsLayoutSize(62, 13, QgsUnitTypes.LayoutMillimeters))

        notes = layout.itemById("notes")
        if self.chkOrdinaryMaxFlood.isChecked():
            notes.setText(
                "Los valores que proporciona esta aplicación para la máxima crecida ordinaria "
                "constituyen estimaciones basadas en asignar, mediante fórmulas aproximadas, "
                "un valor regional al periodo de retorno correspondiente a dicha crecida. "
                "Se trata, por tanto, de valores orientativos que no sustituyen a los valores "
                "obtenidos en los estudios concretos realizados para el deslinde del dominio "
                "público hidráulico."
            )
            label = layout.itemById("subtitle")
            label.setText(
                "INFORME INTERPOLACIÓN DE CUANTILES (MÁXIMA CRECIDA ORDINARIA)"
            )
        else:
            notes.setText("")
            label = layout.itemById("titleresult")
            label.setText("RESULTADO")
            label = layout.itemById("subtitle")
            label.setText(
                "INFORME INTERPOLACIÓN DE CUANTILES (PERIODO DE RETORNO ESTABLECIDO MANUALMENTE)"
            )

        if self.useAlternativeFunction:
            functiontext = "Función de valores extremos de 2 componentes"
            proceduretext = "Procedimiento de ajuste : mínimos cuadrados"
            param1text = f" Parámetro alpha1: {self.alpha1:.4}"
            param2text = f" Parámetro alpha2: {self.alpha2:.4}"
            param3text = f" Parámetro lambda1: {self.lambda1:.4}"
            param4text = f" Parámetro lambda2: {self.lambda2:.4}"
            eqfilename = "funcion_tcev_large.jpg"
        else:
            functiontext = "Función de valores extremos generalizada"
            proceduretext = "Procedimiento de ajuste : mínimos cuadrados"
            param1text = f" Parámetro u: {self.mu:.4f}"
            param2text = f" Parámetro alpha: {self.alpha:.4f}"
            param3text = f" Parámetro k: {self.k:.4f}"
            param4text = ""
            eqfilename = "funcion_extremos_large.jpg"
        function = layout.itemById("function")
        function.setText(functiontext)
        procedure = layout.itemById("procedure")
        procedure.setText(proceduretext)
        param1 = layout.itemById("param1")
        param1.setText(param1text)
        param2 = layout.itemById("param2")
        param2.setText(param2text)
        param3 = layout.itemById("param3")
        param3.setText(param3text)
        param4 = layout.itemById("param4")
        param4.setText(param4text)


        eq = layout.itemById("eq")
        eq.setPicturePath(
            os.path.join(os.path.dirname(__file__), "resources", eqfilename)
        )

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
        mainMap.attemptResize(QgsLayoutSize(202, 128, QgsUnitTypes.LayoutMillimeters))

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
            "", "Informe creado correctamente", level=Qgis.Success, duration=10
        )

        if os.path.exists(imagePath):
            os.remove(imagePath)
        else:
            print("The file does not exist")

    def closeEvent(self, evt):
        if self.marker is not None:
            iface.mapCanvas().scene().removeItem(self.marker)
            self.marker = None
        super().closeEvent(evt)
