"""
***************************************************************************
    __init__.py
***************************************************************************
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
import webbrowser

from qgis.PyQt.QtWidgets import QAction, QToolButton
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMenu, QAction, QToolBar, QPushButton, QLabel


from qgis.PyQt.QtWidgets import (
    QSizePolicy,
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
)

from qgis.core import (
    QgsProject,
    QgsLayerTreeLayer,
    QgsLayerTreeGroup,
    QgsLayerDefinition,
    Qgis,
	QgsApplication,
	QgsMessageLog,
)

from .maxflowdialog import MaxFlowDialog
from .interpolatedmaxflowdialog import InterpolatedMaxFlowDialog
from .rationalmethoddialog import RationalMethodDialog
from .layers import LayersDialog


LYR_FILE = "caumax.qlr"

def classFactory(iface):
    return Caumax(iface)
    dialog = LayersDialog()
    dialog.setDefaultPaths()
#return LayersDialog()


class Caumax:

    returns = [2, 5, 10, 25, 100, 500]

    def __init__(self, iface):
        self.iface = iface
        self.quantilesDialogOpen = False
        self.maxFlowDialogOpen = False
        self.rationalDialogOpen = False
        self.changing = False
		

    def initGui(self):
        self.toolbar = self.iface.addToolBar("CAUMAX")
        button = QPushButton('Mapa de Caudales Máximos\nCAUMAX versión 3.0', self.iface.mainWindow())
        button.clicked.connect(self.mostrar_popup)
        button.setStyleSheet("border: none;")
        self.toolbar.addWidget(button)
       
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "cedex_icon.png")
        icon = QIcon(icon_path)
        QgsApplication.setWindowIcon(icon)
        
        self.action = QAction(icon, 'CAUMAX', self.iface.mainWindow())
        self.action.triggered.connect(self.mostrar_popup)
        self.toolbar.addAction(self.action)

		
        def _icon(ret):
            return QIcon(
                os.path.join(os.path.dirname(__file__), "resources", "%i_on.png" % ret)
            )

        self.layerItems = {}
        self.actionToggleLayer = {}
        for r in self.returns:
            self.actionToggleLayer[r] = QAction(
                _icon(r), str(r), self.iface.mainWindow()
            )
            self.actionToggleLayer[r].setCheckable(True)
            self.toolbar.addAction(self.actionToggleLayer[r])
            self.actionToggleLayer[r].triggered.connect(partial(self.toggleLayer, r))

        self.menu = QMenu("CAUMAX")
        self.menu.setIcon(icon)

        self.actionLoadProject = QAction("Cargar capas CAUMAX", self.iface.mainWindow())
        self.actionLoadProject.triggered.connect(self.loadProject)
        self.menu.addAction(self.actionLoadProject)

        self.menuMaxFlow = QMenu("Mapa de caudales máximos")
        self.actionMaxFlow = QAction(
            "Consulta de capas de caudales máximos", self.iface.mainWindow()
        )
        self.actionMaxFlow.triggered.connect(self.maxFlow)
        self.menuMaxFlow.addAction(self.actionMaxFlow)

        self.actionQuantiles = QAction(
            "Interpolación de cuantiles", self.iface.mainWindow()
        )
        self.actionQuantiles.triggered.connect(self.quantiles)
        self.menuMaxFlow.addAction(self.actionQuantiles)
        self.menu.addMenu(self.menuMaxFlow)

        self.menuRational = QMenu("Método racional")

        self.actionRational = QAction("Método racional", self.iface.mainWindow())
        self.actionRational.triggered.connect(self.rational)
        self.menuRational.addAction(self.actionRational)

        self.actionLayers = QAction(
            "Configurar capas de cálculo", self.iface.mainWindow()
        )
        self.actionLayers.triggered.connect(self.configureLayers)
        self.menuRational.addAction(self.actionLayers)
        self.menu.addMenu(self.menuRational)

        self.menuHelp = QMenu("Ayuda")
        self.actionHelpManual = QAction("Manual de usuario", self.iface.mainWindow())
        self.actionHelpManual.triggered.connect(self.showHelpManual)
        self.menuHelp.addAction(self.actionHelpManual)
        self.actionHelpTechDoc = QAction(u"Memoria técnica", self.iface.mainWindow())
        self.actionHelpTechDoc.triggered.connect(self.showTechDoc)
        self.menuHelp.addAction(self.actionHelpTechDoc)
        self.actionHelpAbout = QAction(u"Acerca de CAUMAX", self.iface.mainWindow())
        self.actionHelpAbout.triggered.connect(self.showAbout)
        self.menuHelp.addAction(self.actionHelpAbout)

        self.menu.addMenu(self.menuHelp)
        self.iface.pluginMenu().addMenu(self.menu)

        self.btnMaxFlow = QToolButton()
        self.btnMaxFlow.setText("Mapa de caudales máximos")
        self.btnMaxFlow.setMenu(self.menuMaxFlow)
        self.btnMaxFlow.setPopupMode(QToolButton.MenuButtonPopup)
        self.btnMaxFlow.clicked.connect(self.btnMaxFlow.showMenu)
        self.toolbar.addWidget(self.btnMaxFlow)

        self.btnRational = QToolButton()
        self.btnRational.setText("Método racional")
        self.btnRational.setMenu(self.menuRational)
        self.btnRational.setPopupMode(QToolButton.MenuButtonPopup)
        self.btnRational.clicked.connect(self.btnRational.showMenu)
        self.toolbar.addWidget(self.btnRational)

        self.btnHelp = QToolButton()
        self.btnHelp.setText("Ayuda")
        self.btnHelp.setMenu(self.menuHelp)
        self.btnHelp.setPopupMode(QToolButton.MenuButtonPopup)
        self.btnHelp.clicked.connect(self.btnHelp.showMenu)
        self.toolbar.addWidget(self.btnHelp)

    def showHelpManual(self):
        webbrowser.open_new(
            os.path.join(os.path.dirname(__file__), "docs", "manual_usuario.pdf")
        )

    def showTechDoc(self):
        webbrowser.open_new(
            os.path.join(os.path.dirname(__file__), "docs", "memoria_tecnica.pdf")
        )

    def showAbout(self):
        webbrowser.open_new(
            os.path.join(os.path.dirname(__file__), "docs", "acerca_de.pdf")
        )

    def _dataFile(self, f):
        return os.path.join(os.path.dirname(__file__), "data", f)

    def toggleLayer(self, ret):
        if not self.changing:
            self.changing = True
        try:
            item = self.layerItems.get(ret)
            if item is not None:
                checked = self.actionToggleLayer[ret].isChecked()
                self.turnOffLayersVisibility()
                self.actionToggleLayer[ret].setChecked(checked)
                item.setItemVisibilityChecked(checked)
            else:
                self.actionToggleLayer[ret].setChecked(False)
        except:
            pass
        finally:
            self.changing = False

    def findLayerItem(self, source, root=None):
        root = root or QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if isinstance(child, QgsLayerTreeLayer):
                childSource = os.path.basename(child.layer().source())
                if source == childSource:
                    return child
            elif isinstance(child, QgsLayerTreeGroup):
                return self.findLayerItem(source, child)

    def mostrar_popup(self):

        popup = QMessageBox(self.iface.mainWindow())
        popup.setWindowTitle('CAUMAX')

        image_path = os.path.join(os.path.dirname(__file__), "templates", "readme.jpg")
        image_label = '<img src="{}">'.format(image_path)
        print ("imagePath = ",image_path, " image_label ",image_label)
		
        popup.setInformativeText(image_label)
       
        popup.exec_()

    def run(self):
        txt = (
            "El principal objetivo de la presente aplicación informática es facilitar la consulta de la información contenida en el mapa de caudales máximos. Dicho mapa abarca el ámbito territorial de las demarcaciones hidrográficas con cuencas intercomunitarias. El mapa de caudales máximos fue elaborado por el Centro de Estudios Hidrográficos del CEDEX en el año 2011 (2009 para la cuenca del Tajo), por encargo de la Dirección General del Agua.<br><br>Junto con las herramientas para facilitar la consulta del mapa de caudales máximos se incluye una herramienta que puede servir de ayuda para realizar estimaciones de los caudales de avenida en aquellos puntos de la red fluvial que, por tener una cuenca vertiente inferior a 50 km2, no están incluidos en el mapa. Esta herramienta permite aplicar el método racional modificado de Témez obteniendo las variables necesarias de forma automática a partir de las coberturas incluidas en la aplicación informática. <br><br>La presente versión de la aplicación sobre QGIS procede de la versión anterior de Caumax 2.3, desarrollada por el Centro de Estudios Hidrográficos del CEDEX sobre gvSIG. La migración de Caumax de gvSIG a QGIS ha sido encargada por la Dirección General del Agua del Ministerio para la Transición Ecológica y el Reto Demográfico a Tragsatec, y ha sido dirigida y supervisada por el Centro de Estudios Hidrográficos del CEDEX."
        )
        imagePath = os.path.dirname(__file__), "templates"
        print ("imagePath = ",imagePath)
        img = os.path.join(
            os.path.dirname(__file__), "templates", "cabecera.jpg"
        )
        txt += f"<p><img src={imagePath}></p>"
        QMessageBox.information(self, "Mapa de Caudales Máximos", txt)	

    def unload(self):
        del self.toolbar
        self.iface.pluginMenu().removeAction(self.menu.menuAction())
        dialog = LayersDialog()
        dialog.setDefaultPaths()

    def quantiles(self):
        if not self.quantilesDialogOpen:
            self.quantilesDialogOpen = True
            dialog = InterpolatedMaxFlowDialog()
            dialog.show()
            dialog.exec_()
            self.quantilesDialogOpen = False

    def maxFlow(self):
        if not self.maxFlowDialogOpen:
            self.maxFlowDialogOpen = True
            dialog = MaxFlowDialog()
            dialog.show()
            dialog.exec_()
            self.maxFlowDialogOpen = False

    def rational(self):
        if not self.rationalDialogOpen:
            self.rationalDialogOpen = True
            dialog = RationalMethodDialog()
            dialog.show()
            dialog.exec_()
            self.rationalDialogOpen = False

    def configureLayers(self):
        dialog = LayersDialog()
        dialog.exec()

    def loadProject(self):
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("CAUMAX_CAPAS")
        if group is not None:
            self.iface.messageBar().pushMessage(
                "CAUMAX",
                "Las capas de CAUMAX ya están en el proyecto actual",
                level=Qgis.Warning,
                duration=5,
            )
        else:
            QgsLayerDefinition.loadLayerDefinition(
                self._dataFile(LYR_FILE), QgsProject.instance(), root
            )
            group = root.findGroup("CAUMAX_CAPAS")
            cloned = group.clone()
            root.insertChildNode(0, cloned)
            root.removeChildNode(group)
            self.setLayerItems()
            dialog = LayersDialog()
            dialog.setDefaultPaths()

    def setLayerItems(self):
        for r in self.returns:
            item = self.findLayerItem("q%i.tif" % r)
            if item is not None:
                self.layerItems[r] = item
                self.layerItems[r].visibilityChanged.connect(
                    partial(self.setButtonState, self.actionToggleLayer[r])
                )
        for r in self.layerItems.keys():
            self.setButtonState(self.actionToggleLayer[r], self.layerItems[r])

    def setButtonState(self, action, item):
        if not self.changing:
            try:
                self.changing = True
                checked = item.itemVisibilityChecked()
                self.turnOffLayersVisibility()
                action.setChecked(checked)
                item.setItemVisibilityChecked(checked)
            except:
                pass
            finally:
                self.changing = False

    def turnOffLayersVisibility(self):
        for ret in self.returns:
            self.actionToggleLayer[ret].setChecked(False)
            self.layerItems[ret].setItemVisibilityChecked(False)
