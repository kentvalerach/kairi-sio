"""
***************************************************************************
    rationalmethoddialog.py
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
import sys
import math
from datetime import date
from functools import partial

from .layers import (
    getValueAtPoint,
    getLayer,
    riverNames,
    usesOnlyDefaultLayers,
    BASINS,
    IGNBASE,
    FLOW_500,
    RIVERS,
    RIVER_NAME_FIELD,
    ORDINARY_PEAK_DISCHARGE_FIELD,
    ZONES,
    CP0T2,
    CP0T5,
    CP0T10,
    CP0T25,
    CP0T100,
    CP0T500,
    ZONE_NAME_FIELD,
    ZONE_BETA,
    ZONE_BETA50,
    ZONE_BETA67,
    ZONE_BETA90,
    MDT,
    STATIONS,
    isLayerVisible,
    isOriginalFlowdirs,
)

from .pointmaptool import PointMapTool
from .basincalculator import BasinCalculator
from .gui_utils import waitcursor

from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsPointXY,
    QgsPrintLayout,
    QgsUnitTypes,
    QgsLayoutSize,
    QgsLayoutExporter,
    QgsReadWriteContext,
    QgsGeometry,
    QgsFeature,
    QgsMessageOutput,
    Qgis,
    QgsWkbTypes,
)
from qgis.gui import QgsMessageBar, QgsVertexMarker, QgsRubberBand
from qgis.utils import iface

from qgis.PyQt import uic
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor, QIntValidator, QIcon
from qgis.PyQt.QtWidgets import (
    QSizePolicy,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QApplication,
)

from qgis.PyQt.QtGui import QPixmap

from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "rationalmethoddialog.ui")
)


class RationalMethodDialog(BASE, WIDGET):

    allReturns = [2, 5, 10, 25, 100, 500]
    p0CorrectorsReturnPeriod = [CP0T2, CP0T5, CP0T10, CP0T25, CP0T100, CP0T500]

    def __init__(self):
        super(RationalMethodDialog, self).__init__(iface.mainWindow())
        self.setupUi(self)

        iconpath = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        self.setWindowIcon(QIcon(iconpath))

        self.editableBoxes = [
            self.txtArea,
            self.txtConcentrationTime,
            self.txtI1Id,
            self.txtRainfall,
            self.txtIntensityFactor,
            self.txtP0,
            self.txtP0Corrector,
        ]

        self.basinCalc = None

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
        self.btnCalculateParameters.clicked.connect(self._calculateParameters)
        self.btnClose.clicked.connect(self.close)
        self.btnReport.clicked.connect(self._createReport)
        print("usesOnlyDefaultLayers = ",usesOnlyDefaultLayers())
        self.btnRecommendedValues.clicked.connect(self.showRecommendedValues)

        self.btnFrequencyLaw.clicked.connect(self.showFrequencyLaw)
        self.btnFitInfo.clicked.connect(self.showFitInfo)
        self.btnFrequencyLaw.setEnabled(False)
        self.btnFitInfo.setEnabled(False)
        self.btnCalculate.setEnabled(False)
        self.btnReport.setEnabled(False)

        self.txtX.textChanged.connect(self._disableButtons)
        self.txtY.textChanged.connect(self._disableButtons)
        self.comboReturnPeriod.currentTextChanged.connect(self.returnPeriodChanged)
        self.comboReturnPeriod.setValidator(QIntValidator(1, 500))
        self.comboReturnPeriod.setCurrentText("100")

        self.txtIntensityFactor.textChanged.connect(self.intensityChanged)
        self.txtConcentrationTime.textChanged.connect(self.concentrationTimeChanged)
        self.txtI1Id.textChanged.connect(self.i1idChanged)
        self.txtRainfall.textChanged.connect(self.rainfallChanged)
        self.txtArea.textChanged.connect(self.areaChanged)

        self.chkOrdinaryMaxFlood.stateChanged.connect(
            self.chkOrdinaryMaxFloodStateChanged
        )

        self.btnReport.setEnabled(False)

        self.populateRivers()

        self.outletMarker = None
        self.maxDistanceMarker = None
        self.rubberBand = None

        for box in self.editableBoxes:
            box.textChanged.connect(partial(self.setTextBoxAsEdited, box))

    def _disableButtons(self):
        self.btnReport.setEnabled(False)
        self.btnCalculate.setEnabled(False)

    def resetEditableBoxesColor(self):
        for box in self.editableBoxes:
            box.setStyleSheet("color: black;")
            box.hasBeenEdited = False

    def setTextBoxAsEdited(self, txtbox):
        txtbox.setStyleSheet("color: red;")
        txtbox.hasBeenEdited = True
        self.btnReport.setEnabled(False)

    def i1idChanged(self):
        self.txtIntensityFactor.setEnabled(False)
        self.calculateIntensityFactor()
            
    def areaChanged(self, text):
        try:
            area = float(text)
            areaCorrection = 1 - (math.log10(area) / 15.0)
            print("area ",area," areaCorrection ",areaCorrection)
            self.txtRainfallCorrection.setText("%.2f" % (areaCorrection * 1))
            returnPeriod = self.returnPeriod()
            noInterpolation = (returnPeriod in self.allReturns and not self.chkOrdinaryMaxFlood.isChecked())
            print("chkOrdinaryMaxFlood ",self.chkOrdinaryMaxFlood.isChecked()," noInterpolation ",noInterpolation)
            if noInterpolation:
                rainfall = float(self.txtRainfall.text())
                self.txtCorrectedRainfall.setText("%.2f" % (areaCorrection * rainfall))
            else:
                print("area ",area," areaCorrection ",areaCorrection)
        except:
            self.txtRainfallCorrection.setText("")

    def rainfallChanged(self, text):
        try:
            rainfallCorrection = float(self.txtRainfallCorrection.text())
            rainfall = float(text)
            print("rainfall ",rainfall, " rainfallCorrection ",rainfallCorrection)
            self.txtCorrectedRainfall.setText("%.2f" % (rainfall * rainfallCorrection))
        except:
            self.txtCorrectedRainfall.setText("")

    def concentrationTimeChanged(self, text):   
        try:
            if not self.txtIntensityFactor.hasBeenEdited:
                self.calculateIntensityFactor()
            kc = 1 + (math.pow(float(self.txtConcentrationTime.text()), 1.25) / (math.pow(float(self.txtConcentrationTime.text()), 1.25) + 14))
            self.txtUniformity.setText("%.2f" % kc)
        except:
            self.txtConcentrationTime.setText("")

    def calculateIntensityFactor(self):
        self.txtIntensityFactor.blockSignals(True)
        try:
            tc = float(self.txtConcentrationTime.text())
            i1id = float(self.txtI1Id.text())
            intensityFactor = math.pow(
                i1id,
                ((math.pow(28, 0.1) - math.pow(tc, 0.1)) / (math.pow(28, 0.1) - 1)),
            )
            self.txtIntensityFactor.setText("%.2f" % intensityFactor)
        except:
            self.txtIntensityFactor.setText("")
        finally:
            self.txtIntensityFactor.blockSignals(False)

    def intensityChanged(self):
        self.txtI1Id.setEnabled(False)

    def _getmedian(self, returnPeriod):
        return -math.log(math.log(returnPeriod/(returnPeriod-1)))

    def _canvas(self):
        periods =  range(self.returnPeriodsForFitting[0], self.returnPeriodsForFitting[-1] + 1)
        showperiods = [self._getmedian(x) for x in periods ]
        #showkeyPeriods = [0.366513,1.499939987,2.250367327,3.198534261,4.600149227,6.213607264]
        values = [self._getInterpolatedFlow(x) for x in periods]
        keyPeriods = self.returnPeriodsForFitting
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
        print("flow ",flow, " flow_calculated ",self._getInterpolatedFlow(returnPeriod)," returnPeriodsForFitting[-1] ",self.returnPeriodsForFitting[-1])
        self._ax.plot(self._getmedian(returnPeriod), self._getInterpolatedFlow(returnPeriod), "go")
        self._ax.set_xticks(showkeyPeriods,minor=False)

        if len(keyPeriods) == 4:
            self._ax.set_xticklabels(['2','5','10','25'], minor=False)
        else:
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

    def setFittedValues(self, returnPeriods, qs):
        self.returnPeriodsForFitting = returnPeriods
        self.valuesForFitting = qs

        def frange(start, end, step):
            while start < end:
                yield start
                start += step

        minDiff = sys.float_info.max

        self.alpha = 0.0
        self.mu = 0.0
        self.k = -0.5
        limit = (qs[1] + qs[-2]) / 4.0
        interval = limit / 100
        for testAlpha in frange(0, limit, interval):
            for testMu in frange(0, limit, interval):
                for testK in frange(-0.5, 0, 0.01):
                    diff = self.getSquaredDiff(
                        testAlpha, testMu, testK, returnPeriods, qs
                    )
                    if diff < minDiff:
                        minDiff = diff
                        self.alpha = testAlpha
                        self.mu = testMu
                        self.k = testK

    def getSquaredDiff(self, alpha, mu, k, returnPeriods, qs):
        diff = 0
        total = 0
        fs = [(1 - 1 / r) for r in returnPeriods]
        for f, q in zip(fs, qs):
            v = mu + alpha / k * (1 - math.pow(-math.log(f), k))
            diff = v - q
            total += diff * diff

        return total

    def showFitInfo(self):
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

    def _getInterpolatedFlow(self, returnPeriod):
        prob = 1 - 1.0 / returnPeriod
        return self.mu + self.alpha / self.k * (1 - math.pow(-math.log(prob), self.k))

    def returnPeriodChanged(self):
        self.btnReport.setEnabled(False)
        self.btnCalculate.setEnabled(False)

    def populateRivers(self):
        self.comboRiverName.addItems(riverNames())

    def zoomToRiverName(self):
        name = self.comboRiverName.currentText()
        layer = getLayer(RIVERS)
        layer.selectByExpression("\"%s\" = '%s'" % (RIVER_NAME_FIELD, name))
        box = layer.boundingBoxOfSelected()
        iface.mapCanvas().setExtent(box)
        iface.mapCanvas().refresh()

    def chkOrdinaryMaxFloodStateChanged(self, state):
        if state == Qt.Checked:
            self.comboReturnPeriod.setEnabled(False)
        else:
            self.comboReturnPeriod.setEnabled(True)
        self.btnCalculate.setEnabled(False)
        self.btnReport.setEnabled(False)

    def showRecommendedValues(self):
        logo = os.path.join(
            os.path.dirname(__file__), "resources", "cedex_icon.png"
        )
        pt = self.outletPoint()
        if pt is None:
            return

        zone = getValueAtPoint(ZONES, pt, ZONE_NAME_FIELD)
        if zone is None:
            QMessageBox.warning(
                self,
                "Error de localización",
                "Se ha seleccionado un punto fuera de la cuenca.",
            )

            return


        beta = getValueAtPoint(ZONES, pt, ZONE_BETA)
        beta50 = getValueAtPoint(ZONES, pt, ZONE_BETA50)
        beta67 = getValueAtPoint(ZONES, pt, ZONE_BETA67)
        beta90 = getValueAtPoint(ZONES, pt, ZONE_BETA90)

        txt = f"""<p>El punto seleccionado está sobre la región nº {zone}</p>
                <p>____________________________________________________________</p>
                <ul>
                <li>Valor medio: {beta: .2f}\n</li>
                <li>Intervalo confianza 50%: ± {beta50:.2f}\n</li>
                <li>Intervalo confianza 67%: ± {beta67:.2f}\n</li>
                <li>Intervalo confianza 90%: ± {beta90:.2f}\n</li>
                </ul>
                """

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.setText(txt)
        msg_box.setWindowTitle("Valores recomendados del coeficiente corrector de P0")
        msg_box.exec_()

    def outletPoint(self):
        try:
            x = float(self.txtX.text())
            y = float(self.txtY.text())
            pt = QgsPointXY(x, y)
            zone = getValueAtPoint(BASINS, pt, field="DEMAR")
            if zone is None:
                QMessageBox.warning(
                    self,
                    "Error de localización",
                    "Se ha seleccionado un punto fuera de la cuenca.",
                )

            else:
                return pt
        except:
            QMessageBox.warning(
                self,
                "Error de localización",
                "Las coordenadas introducidas no son válidas.",
            )

    def _calculate(self):
        self.calculate()

    @waitcursor
    def calculate(self):
        pt = self.outletPoint()
        if pt is None:
            return

        returnPeriod = self.returnPeriod()
        if returnPeriod is None:
            return

        zone = getValueAtPoint(ZONES, pt, ZONE_NAME_FIELD)
        if zone in [72, 73, 84, 821, 822]:
            if returnPeriod > 25:
                QMessageBox.warning(
                    self,
                    "Método racional",
                    f"El punto seleccionado está sobre la región nº {zone}\n"
                    "sobre la cual no se puede aplicar el método racional "
                    "para periodos de retorno mayores de 25 años",
                )
                return
            else:
                returnPeriods = [2, 5, 10, 25]
        else:
            returnPeriods = [2, 5, 10, 25, 100, 500]

        area = float(self.txtArea.text())
        if area > 50:
            QMessageBox.warning(
                self,
                "Método racional",
                "Cuenca mayor de 50 km². Consulte las capas precalculadas",
            )

            return
        if self.outletMarker is None:
            self.outletMarker = QgsVertexMarker(iface.mapCanvas())
            self.outletMarker.setIconSize(8)
            self.outletMarker.setPenWidth(4)
        self.outletMarker.setCenter(pt)

        self.btnFitInfo.setEnabled(False)
        self.btnFrequencyLaw.setEnabled(False)
        self.btnReport.setEnabled(False)
        try:
            v = getValueAtPoint(MDT, pt)
            someflownegative = False
            if v is None:
                QMessageBox.warning(
                    self,
                    "Método racional",
                    "No es posible calcular el caudal en el punto especificado.",
                )

            else:
                self.txtIntensity.blockSignals(True)
                self.txtIntensityFactor.blockSignals(True)
                self.txtI1Id.blockSignals(True)
                intensityFactor = float(self.txtIntensityFactor.text())
                p0 = float(self.txtP0.text())
                if  ( p0 < 0 ):
                    QMessageBox.warning(self,"Método racional","El coeficiente corrector de P0 debe ser mayor o igual a cero",)

                p0Corrector = float(self.txtP0Corrector.text())
                if  ( p0Corrector < 0 ):
                    QMessageBox.warning(self,"Método racional","El coeficiente corrector de P0 debe ser mayor o igual a cero",)

                correctedP0 = p0 * p0Corrector
                if (
                    returnPeriod in returnPeriods
                    and not self.chkOrdinaryMaxFlood.isChecked()
                ):
                    correctedRainfall = float(self.txtCorrectedRainfall.text())
                    p0CorrectorReturnPeriod = float(
                        self.txtP0CorrectorReturnPeriod.text()
                    )
                    correctedP0 *= p0CorrectorReturnPeriod
                    intensity, runoffCoef = self.factorsFromRainfall(
                        correctedRainfall, correctedP0, intensityFactor
                    )
                    self.txtCFactor.setText("%.2f" % runoffCoef)
                    self.txtIntensity.setText("%.2f" % intensity)
                    self.txtCorrectedP0.setText("%.2f" % correctedP0)
                    flow = self.getFlow(runoffCoef, intensity)
                else:
                    flows = []
                    areaCorrection = float(self.txtRainfallCorrection.text())
                    for i, period in enumerate(returnPeriods):
                        correctedRainfall = self.basinCalc.rain[period] * areaCorrection
                        p0CorrectorReturnPeriod = getValueAtPoint(
                            ZONES, pt, self.p0CorrectorsReturnPeriod[i]
                        )
                        intensity, runoffCoef = self.factorsFromRainfall(
                            correctedRainfall,
                            correctedP0 * p0CorrectorReturnPeriod,
                            intensityFactor,
                        )
                        flows.append(self.getFlow(runoffCoef, intensity))
                    self.setFittedValues(returnPeriods, flows)
                    flow = self._getInterpolatedFlow(returnPeriod)
                    self.txtCFactor.setText("")
                    self.txtIntensity.setText("")
                    if (True in [t <= 0 for t in flows]):
                        someflownegative = True
                if flow < 0 or someflownegative == True:
                    self.txtResultFlow.setText("")
                    if flow < 0:
                        QMessageBox.warning(
                            self,
                            "Método racional",
                            "No puede realizarse el cálculo porque el coeficiente corrector"
                            " adoptado genera un caudal igual a cero para el periodo de retorno seleccionado.",
                        )
                    if someflownegative == True:
                        QMessageBox.warning(
                            self,
                            "Método racional",
                            "No puede realizarse el cálculo porque el coeficiente corrector"
                            " adoptado genera caudales igual a cero para alguno de los periodos de retorno.",
                        )
                else:
                    if usesOnlyDefaultLayers():
                        self.btnReport.setEnabled(True)
                        if self.chkOrdinaryMaxFlood.isChecked():
                            self.txtResultReturnPeriod.setText("%.1f" % returnPeriod)
                        else:
                            self.txtResultReturnPeriod.setText("%.0f" % returnPeriod)

                        self.txtResultFlow.setText("%.i" % round(flow))
                    else:

                        msgBox = QMessageBox()
                        msgBox.setWindowTitle("Método racional")
                        msgBox.setText("Se han asignado capas de información para el cálculo que no coinciden con las definidas por defecto en la aplicación. Pulse 'Aceptar' para confirmar que desea realizar el cálculo.\nPara calcular con las capas definidas por defecto en la aplicación pulse Cancelar y vaya al menú 'Configurar capas de cálculo' para asignar las capas por defecto.")
                        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
                        msgBox.setDefaultButton(QMessageBox.Yes)  
                        buttonyes = msgBox.button(QMessageBox.Yes)
                        buttonyes.setText("Aceptar")
                        result = msgBox.exec()

                        if result == QMessageBox.Yes:
                            self.btnReport.setEnabled(False)
                            if self.chkOrdinaryMaxFlood.isChecked():
                                self.txtResultReturnPeriod.setText("%.1f" % returnPeriod)
                            else:
                                self.txtResultReturnPeriod.setText("%.0f" % returnPeriod)

                            self.txtResultFlow.setText("%.i" % round(flow))

                        else:
                            self.btnReport.setEnabled(False)
                            self.txtResultReturnPeriod.setText("")
                            self.txtResultFlow.setText("")
                            print("usesOnlyDefaultLayers = ",usesOnlyDefaultLayers())

                    interpolation = (
                        returnPeriod not in returnPeriods
                        or self.chkOrdinaryMaxFlood.isChecked()
                    )
                    self.btnFrequencyLaw.setEnabled(interpolation)
                    self.btnFitInfo.setEnabled(interpolation)
        except:
            QMessageBox.warning(
                self,
                "Método racional",
                "Valores incorrectos",
            )

        finally:
            self.txtIntensity.blockSignals(False)
            self.txtIntensityFactor.blockSignals(False)
            self.txtI1Id.blockSignals(False)

    def getFlow(self, runoff, intensity):
        area = float(self.txtArea.text())
        uniformity = float(self.txtUniformity.text())
        return (runoff * intensity * area * uniformity) / 3.6

    def returnPeriod(self):
        if self.chkOrdinaryMaxFlood.isChecked():
            pt = self.outletPoint()
            if pt is None:
                return None
            returnPeriod = getValueAtPoint(ZONES, pt, ORDINARY_PEAK_DISCHARGE_FIELD)
        else:
            try:
                returnPeriod = float(self.comboReturnPeriod.currentText())
            except:
                QMessageBox.warning(self,"Método racional","Valores incorrectos",)

        return returnPeriod

    def _calculateParameters(self):
        self.calculateParameters()

    @waitcursor
    def calculateParameters(self):

        self.btnReport.setEnabled(False)
        self.btnCalculate.setEnabled(False)

        pt = self.outletPoint()
        if pt is None:
            return

        returnPeriod = self.returnPeriod()
        if returnPeriod is None:
            return
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

        if isOriginalFlowdirs():
            v = getValueAtPoint(FLOW_500, pt)
            if v is not None:
                QMessageBox.warning(
                    self,
                    "Método racional",
                    "Cuenca mayor de 50 km². Consulte las capas precalculadas",
                )
                return



        zone = getValueAtPoint(ZONES, pt, ZONE_NAME_FIELD)
        if zone in [72, 73, 84, 821, 822] and returnPeriod > 25:
            QMessageBox.warning(
                self,
                "Método racional",
                "El punto seleccionado está sobre la región nº %i\n"
                "sobre la cual no se puede aplicar el método racional "
                "para periodos de retorno mayores de 25 años." % zone,
            )
            return

        v = getValueAtPoint(MDT, pt)
        if v is None:
            QMessageBox.warning(
                self,
                "Método racional",
                "El punto seleccionado no se encuentra dentro de las capas de cálculo",
            )
            return

        try:
            self.txtIntensity.blockSignals(True)
            self.txtIntensityFactor.blockSignals(True)
            self.txtI1Id.blockSignals(True)
            self.resetEditableBoxesColor()

            if self.basinCalc is None:
                self.basinCalc = BasinCalculator()
            self.basinCalc.calculate(pt)

            if self.basinCalc.area / 1000000 >= 50:
                QMessageBox.warning(
                    self,
                    "Método racional",
                    "Cuenca mayor de 50 km². Consulte las capas precalculadas",
                )

                return

            if self.basinCalc.xMaxDistance is not None:
                if self.maxDistanceMarker is None:
                    self.maxDistanceMarker = QgsVertexMarker(iface.mapCanvas())
                    self.maxDistanceMarker.setIconSize(8)
                    self.maxDistanceMarker.setPenWidth(4)
                    self.maxDistanceMarker.setColor(QColor(0, 255, 0))
                self.maxDistanceMarker.setCenter(
                    QgsPointXY(self.basinCalc.xMaxDistance, self.basinCalc.yMaxDistance)
                )

            minArea = 1000000 * float(QSettings().value("/caumax/basinsize", 10))
            minAreakm2 = minArea / 1000000
            areaKm = self.basinCalc.area / 1000000

            if self.basinCalc.area < minArea:
                QApplication.setOverrideCursor(Qt.ArrowCursor)
                QMessageBox.warning(
                    self,
                    "Método racional",
                    f"El punto seleccionado tiene  una cuenca inferior a {minAreakm2} km², "
                    "por lo que dada la resolución de las capas incluidas en la aplicación, "
                    "los resultados podrían no tener suficiente precisión.\n\n"
                    f"El área que genera el punto seleccionado es de {areaKm} km².\n\n"
                    "Si ha cargado en la aplicación capas con mayor resolución, o si, a pesar "
                    "de todo, desea realizar el cálculo para ese punto, puede modificar el valor "
                    "de la cuenca mínima de cálculo en el menu 'Configurar capas de cálculo'.\n\n"
                    "En cualquier caso, se recomienda tener en cuenta que no se aconseja la "
                    "aplicación del método racional en cuencas con un tiempo de concentración "
                    "inferior a 0.25h.",
                )
                QApplication.restoreOverrideCursor()
                return

            self.txtArea.setText("%.3f" % (areaKm))
            tc = self.basinCalc.concentrationTime
            self.txtConcentrationTime.setText("%.3f" % tc)
            self.txtDistance.setText("%.3f" % self.basinCalc.maxDistance)
            self.txtHighest.setText("%.3f" % self.basinCalc.maxH)
            self.txtLowest.setText("%.3f" % self.basinCalc.minH)
            areaCorrection = 1 - (math.log10(areaKm) / 15.0)
            self.txtRainfallCorrection.setText("%.2f" % areaCorrection)
            self.txtI1Id.setText("%.2f" % self.basinCalc.i1id)
            intensityFactor = math.pow(
                self.basinCalc.i1id,
                ((math.pow(28, 0.1) - math.pow(tc, 0.1)) / (math.pow(28, 0.1) - 1)),
            )
            self.txtIntensityFactor.setText("%.2f" % intensityFactor)
            kc = 1 + (math.pow(tc, 1.25) / (math.pow(tc, 1.25) + 14))
            self.txtUniformity.setText("%.2f" % kc)
            self.txtP0.setText("%.2f" % self.basinCalc.p0)
            if self.rubberBand is None:
                self.rubberBand = QgsRubberBand(
                    iface.mapCanvas(), QgsWkbTypes.PolygonGeometry
                )
                self.rubberBand.setColor(QColor(255, 0, 0, 127))
            else:
                self.rubberBand.setToGeometry(QgsGeometry())
            for geom in self.basinCalc.basinGeometry:
                rings = geom.asPolygon()
                if len(rings) == 1:
                    self.rubberBand.addGeometry(geom)

            if returnPeriod in self.allReturns and not self.chkOrdinaryMaxFlood.isChecked():
                rainfall = self.basinCalc.rain[returnPeriod]
                self.txtRainfall.setText("%.2f" % rainfall)
                self.txtRainfall.setEnabled(True)
                correctedRainfall = areaCorrection * rainfall
                self.txtCorrectedRainfall.setText("%.2f" % correctedRainfall)
                p0CorrectorReturnPeriod = getValueAtPoint(
                    ZONES,
                    pt,
                    self.p0CorrectorsReturnPeriod[self.allReturns.index(returnPeriod)],
                )
                self.txtP0CorrectorReturnPeriod.setText(
                    "%.2f" % p0CorrectorReturnPeriod
                )
            else:
                self.txtRainfall.setText("")
                self.txtRainfall.setEnabled(False)
                self.txtCorrectedRainfall.setText("")
                self.txtIntensity.setText("")
                self.txtCFactor.setText("")
                self.txtP0CorrectorReturnPeriod.setText("")
        finally:
            self.txtIntensity.blockSignals(False)
            self.txtIntensityFactor.blockSignals(False)
            self.txtI1Id.blockSignals(False)
        self.txtCorrectedP0.setText("")

        self.btnCalculate.setEnabled(True)
        self.txtI1Id.setEnabled(True)
        self.txtIntensityFactor.setEnabled(True)
		
        self.txtResultFlow.setText("")
        self.txtResultReturnPeriod.setText("")

        self.resetEditableBoxesColor()

        if self.chkOrdinaryMaxFlood.isChecked():
            QApplication.setOverrideCursor(Qt.ArrowCursor)
            warningText = (
                "Los valores que proporciona esta aplicación para la máxima crecida ordinaria "
                "constituyen estimaciones basadas en asignar, mediante fórmulas aproximadas, "
                "un valor regional al periodo de retorno correspondiente a dicha crecida.\n\n"
                "Se trata, por tanto, de valores orientativos que no sustituyen a los valores "
                "obtenidos en los estudios concretos realizados para el deslinde del dominio "
                "público hidráulico."
            )
            QMessageBox.warning(self, "Aviso", warningText)
            QApplication.restoreOverrideCursor()

    def setCorrectedP0(self):
        returnPeriod = self.returnPeriod()
        if returnPeriod is None:
            return None
        p0Corrector = float(self.txtP0Corrector.text())
        if returnPeriod in self.allReturns:
            p0CorrectorReturnPeriod = float(self.txtP0CorrectorReturnPeriod.text())
            correctedP0 = self.basinCalc.p0 * p0Corrector * p0CorrectorReturnPeriod
        else:
            correctedP0 = None

        if correctedP0 is None:
            self.txtCorrectedP0.setText("")
        else:
            self.txtCorrectedP0.setText("%.2f" % correctedP0)
        return correctedP0

    def factorsFromRainfall(self, correctedRainfall, p0, intensityFactor):
        intensity = correctedRainfall / 24.0 * intensityFactor
        if (p0==0):
            ratio = correctedRainfall
        else:
            ratio = correctedRainfall / p0
        runoffCoef = ((ratio - 1) * (ratio + 23)) / math.pow(ratio + 11, 2.0)
        return intensity, runoffCoef

    def _countVertices(self, geom):
        vertices = 0
        rings = geom.asPolygon()
        for ring in rings:
            vertices += len(ring)
        return vertices

    def getPoint(self):
        canvas = iface.mapCanvas()
        canvas.setMapTool(self.tool)
        self.showMinimized()

    def updatePoint(self, point, button):
        self.txtX.setText("%.1f" % (point.x()))
        self.txtY.setText("%.1f" % (point.y()))
        if self.outletMarker is None:
            self.outletMarker = QgsVertexMarker(iface.mapCanvas())
        self.outletMarker.setCenter(point)
        self.outletMarker.setIconSize(8)
        self.outletMarker.setPenWidth(4)

    def pointPicked(self):
        canvas = iface.mapCanvas()
        canvas.setMapTool(self.prevMapTool)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _createReport(self):
        self.createReport()

    @waitcursor
    def createReport(self):
        pt = self.outletPoint()
        if pt is None:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Informe", "", "Archivos PDF (*.pdf)"
        )
        if not filename:
            return

        basinlayer = QgsVectorLayer("Polygon?crs=epsg:25830", "Cuenca", "memory")
        prov = basinlayer.dataProvider()
        for geom in self.basinCalc.basinGeometry:
            rings = geom.asPolygon()
            if len(rings) == 1:
                feat = QgsFeature()
                feat.setGeometry(geom)
                prov.addFeatures([feat])
        basinlayer.updateExtents()
        stylefile = os.path.join(os.path.dirname(__file__), "data", "basin.qml")
        basinlayer.loadNamedStyle(stylefile)

        flow = self.txtResultFlow.text()
        returnPeriod = self.returnPeriod()

        noInterpolation = (
            returnPeriod in self.allReturns and not self.chkOrdinaryMaxFlood.isChecked()
        )
        if noInterpolation:
            templateFilename = os.path.join(
                os.path.dirname(__file__), "templates", "rational1.qpt"
            )
        else:
            templateFilename = os.path.join(
                os.path.dirname(__file__), "templates", "rational2.qpt"
            )
        document = QDomDocument()
        with open(templateFilename) as f:
            document.setContent(f.read())
        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.loadFromTemplate(document, QgsReadWriteContext())

        zone = getValueAtPoint(BASINS, pt, field="DEMAR")
        title = layout.itemById("title")
        title.setText(f"Demarcación Hidrográfica del {zone.title()}")

        modified = layout.itemById("modified")
        if self.txtArea.hasBeenEdited:
            areaKm = f"{(self.basinCalc.area / 1000000):.3f}/{float(self.txtArea.text()):.3f} (*)"
            modified.setVisible(True)
        else:
            areaKm = f"{(self.basinCalc.area / 1000000):.3f}"
        
        areaCorrectionOginial = 1 - (math.log10(self.basinCalc.area / 1000000) / 15.0)
        areaCorrection = 1 - (math.log10(float(self.txtArea.text())) / 15.0)
        print("area original ",self.basinCalc.area,"area ",float(self.txtArea.text())," areaCorrection ",areaCorrection," areaCorrectionOginial ",areaCorrectionOginial)
        if self.txtConcentrationTime.hasBeenEdited:
            tc = f"{self.basinCalc.concentrationTime:.2f}/{float(self.txtConcentrationTime.text()):.2f} (*)"
            modified.setVisible(True)
        else:
            tc = f"{self.basinCalc.concentrationTime:.2f}"

        if self.txtI1Id.hasBeenEdited:
            i1id = f"{self.basinCalc.i1id: .1f}/{float(self.txtI1Id.text())} (*)"
            modified.setVisible(True)
        else:
            i1id = f"{self.basinCalc.i1id: .1f}"

        if self.txtIntensityFactor.hasBeenEdited:
            intensityFactor = math.pow(
                self.basinCalc.i1id,
                (
                    (
                        math.pow(28, 0.1)
                        - math.pow(self.basinCalc.concentrationTime, 0.1)
                    )
                    / (math.pow(28, 0.1) - 1)
                ),
            )
            intensityFactor = (
                f"{intensityFactor:.3f}/{float(self.txtIntensityFactor.text()):.2f} (*)"
            )
            modified.setVisible(True)
        else:
            intensityFactor = f"{float(self.txtIntensityFactor.text()):.2f}"

        if self.txtP0.hasBeenEdited:
            p0 = f"{self.basinCalc.p0:.3f}/{float(self.txtP0.text()):.3f} (*)"
            modified.setVisible(True)
        else:
            p0 = f"{float(self.txtP0.text()):.3f}"
        p0Corrector = float(self.txtP0Corrector.text())

        kc = float(self.txtUniformity.text())
        if noInterpolation:
            if self.txtRainfall.hasBeenEdited:
                rainfall = f"{self.basinCalc.rain[returnPeriod]:.3f}/{float(self.txtRainfall.text()):.3f} (*)"
                correctedRainfall = float(self.txtRainfall.text()) * areaCorrection
                modified.setVisible(True)
            else:
                rainfall = f"{self.basinCalc.rain[returnPeriod]:.3f}"
                correctedRainfall = self.basinCalc.rain[returnPeriod] * areaCorrection

            intensity = float(self.txtIntensity.text())
            runoffCoef = float(self.txtCFactor.text())

            p0CorrectorReturnPeriod = getValueAtPoint(
                ZONES,
                pt,
                self.p0CorrectorsReturnPeriod[self.allReturns.index(returnPeriod)],
            )
            
            correctedP0 = float(self.txtCorrectedP0.text())
            
            paramstxt = (f"X utm: {pt.x()} - Y utm: {pt.y()}\n"
            f"Área (km²): {areaKm}\n"
            f"Tiempo de concentración (h): {tc}\n"
            f"Distancia al punto más alejado (m): {self.basinCalc.maxDistance:.0f}\n"
            f"Cota del punto más alejado (msnm): {self.basinCalc.maxH}\n"
            f"Cota del punto de cálculo (msnm): {self.basinCalc.minH}\n"
            f"Precipitación (mm): {rainfall}\n"
            f"Factor reductor por área: {areaCorrection:.3f}\n"
            f"Precipitación corregida (mm): {correctedRainfall:.3f}\n")
            
            paramstxt2 = (f"Factor de intensidad: {intensityFactor}\n"
            f"Factor de torrencialidad (I1/Id): {i1id}\n"
            f"Intensidad (I) (mm/h): {intensity:.3f}\n"
            f"P0 (mm): {p0}\n"
            f"Coeficiente corrector de P0: {p0Corrector} \n"
            f"Coeficiente corrector de P0 según periodo de retorno: {p0CorrectorReturnPeriod}\n"
            f"P0 corregido (mm): {correctedP0} \n"
            f"Coeficiente de escorrentía (C): {runoffCoef:.3f} \n"
            f"Coeficiente de uniformidad (K): {kc:.3f}\n")

            label = layout.itemById("params")
            label.setText(paramstxt)
            label = layout.itemById("params2")
            label.setText(paramstxt2)
            label = layout.itemById("result")
            label.setText(
                f"Periodo de retorno (años): {returnPeriod:.0f}\n Caudal (m³/s): {flow}"
            )
            label = layout.itemById("date")
            label.setText("Fecha: " + str(date.today().strftime("%d/%m/%Y")))
        else:
            paramstxt = (f"X utm: {pt.x()} - Y utm: {pt.y()}\n"
            f"Área (km²): {areaKm:}\n"
            f"Tiempo de concentración (h): {tc}\n"
            f"Distancia al punto más alejado (m): {self.basinCalc.maxDistance:.0f}\n"
            f"Cota del punto más alejado (msnm): {self.basinCalc.maxH}\n"
            f"Cota del punto de cálculo (msnm): {self.basinCalc.minH}\n"
            f"Factor reductor por área: {areaCorrection:.3f}\n"
            f"Factor de intensidad: {intensityFactor}\n"
            f"Factor de torrencialidad (I1/Id): {i1id}\n"
            f"P0 (mm): {p0} \n"
            f"Coeficiente corrector de P0: {p0Corrector}\n"
            f"Coeficiente de uniformidad (K): {kc:.3f} \n")
            label = layout.itemById("params")
            label.setText(paramstxt)
            label = layout.itemById("result")
            if float(returnPeriod.is_integer()):
                label.setText(
                    f"Periodo de retorno (años): {returnPeriod:.0f}\n"
                    f"Caudal (m³/s): {flow}\n"
                )
            else:
                label.setText(
                    f"Periodo de retorno (años): {returnPeriod:.1f}\n"
                    f"Caudal (m³/s): {flow}\n"
                )
            label = layout.itemById("date")
            label.setText("Fecha: " + str(date.today().strftime("%d/%m/%Y")))

            notes = layout.itemById("notes")
            if self.chkOrdinaryMaxFlood.isChecked():
                warningText = (
                    "Los valores que proporciona esta aplicación para la máxima crecida ordinaria "
                    "constituyen estimaciones basadas en asignar, mediante fórmulas aproximadas, "
                    "un valor regional al periodo de retorno correspondiente a dicha crecida.\n\n "
                    "Se trata, por tanto, de valores orientativos que no sustituyen a los valores "
                    "obtenidos en los estudios concretos realizados para el deslinde del dominio "
                    "público hidráulico."
                )
                notes.setText(warningText)
                label = layout.itemById("resulttitle")
                label.setText("RESULTADO (MAXIMA CRECIDA ORDINARIA)")
                label = layout.itemById("subtitle")
                label.setText(
                    "INFORME CÁLCULO CON MÉTODO RACIONAL Y MÁXIMA CRECIDA ORDINARIA"
                )
            else:
                notes.setText("")
            paramstxt = (
            f" Parámetro u: %.4f\n Parámetro alpha: %.4f\n Parámetro k: %.4f"
            % (self.mu, self.alpha, self.k)
            )
            params = layout.itemById("paramsinterpolation")
            params.setText(paramstxt)
            eq = layout.itemById("eq")
            eq.setPicturePath(
                os.path.join(
                    os.path.dirname(__file__), "resources", "funcion_extremos_large.jpg"
                )
            )

            canvas = self._canvas()
            imagePath = os.path.splitext(filename)[0] + ".png"
            canvas.figure.savefig(imagePath, bbox_inches="tight",dpi=300)
            graph = layout.itemById("graph")
            graph.setPicturePath(imagePath)

        bufferDist = 10000
        r = basinlayer.extent()
        r.grow(bufferDist)

        scale = layout.itemById("scale")
        scale.attemptResize(QgsLayoutSize(142, 13, QgsUnitTypes.LayoutMillimeters))

        pointlayer = QgsVectorLayer("Point?crs=epsg:25830", "Punto", "memory")
        prov = pointlayer.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(pt))
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
        layers = [pointlayer, rivers, basinlayer, basins, baselayer]
        if isLayerVisible(stations):
            layers.insert(0, stations)
        mainMap.setLayers(layers)
        mainMap.setExtent(r)
        h = 162 if noInterpolation else 126
        mainMap.attemptResize(QgsLayoutSize(202, h, QgsUnitTypes.LayoutMillimeters))

        header = layout.itemById("header")
        header.setPicturePath(
            os.path.join(os.path.dirname(__file__), "templates", "cabecera.jpg")
        )

        legend = layout.itemById("legend")
        root = legend.model().rootGroup()
        root.addLayer(pointlayer)
        root.addLayer(rivers)
        root.addLayer(basinlayer)
        root.addLayer(basins)
        if isLayerVisible(stations):
            root.addLayer(stations)

        exporter = QgsLayoutExporter(layout)
        exporter.exportToPdf(filename, QgsLayoutExporter.PdfExportSettings())
        self.bar.pushMessage(
            "", "Informe creado correctamente", level=Qgis.Success, duration=10
        )
        if noInterpolation:
            print("No Interpolation")
        else:
            if os.path.exists(imagePath):
                os.remove(imagePath)
            else:
                print("The file does not exist")



    def closeEvent(self, evt):
        if self.outletMarker is not None:
            iface.mapCanvas().scene().removeItem(self.outletMarker)
            self.outletMarker = None
        if self.maxDistanceMarker is not None:
            iface.mapCanvas().scene().removeItem(self.maxDistanceMarker)
            self.maxDistanceMarker = None
        if self.rubberBand is not None:
            iface.mapCanvas().scene().removeItem(self.rubberBand)
            self.rubberBand = None
        super().closeEvent(evt)
