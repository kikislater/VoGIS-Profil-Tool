# -*- coding: utf-8 -*-
"""
/***************************************************************************
 VoGISProfilToolMainDialog
                                 A QGIS plugin
 VoGIS ProfilTool
                             -------------------
        begin                : 2013-05-28
        copyright            : (C) 2013 by BergWerk GIS
        email                : wb@BergWerk-GIS.at
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import traceback
import unicodedata
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import QGis
from qgis.core import QgsMessageLog
from qgis.core import QgsGeometry
from qgis.core import QgsPoint
from qgis.gui import QgsRubberBand
from ui.ui_vogisprofiltoolmain import Ui_VoGISProfilToolMain
#from bo.raster import Raster
from util.u import Util
from bo.settings import enumModeLine, enumModeVertices
from bo.rasterCollection import RasterCollection
from bo.raster import Raster
from util.ptmaptool import ProfiletoolMapTool
from util.createProfile import CreateProfile
from vogisprofiltoolplot import VoGISProfilToolPlotDialog


class VoGISProfilToolMainDialog(QDialog):
    def __init__(self, interface, settings):

        self.settings = settings
        self.iface = interface
        self.selectingVisibleRasters = False
        self.thread = None

        QDialog.__init__(self, interface.mainWindow())

        # Set up the user interface from Designer.
        self.ui = Ui_VoGISProfilToolMain()
        self.ui.setupUi(self)

        if self.settings.onlyHektoMode is True:
            self.ui.IDC_widRaster.hide()
            self.adjustSize()

        validator = QIntValidator(-32768, 32768, self)
        self.ui.IDC_tbNoDataExport.setValidator(validator)

        self.ui.IDC_tbFromX.setText('-30000')
        self.ui.IDC_tbFromY.setText('240000')
        self.ui.IDC_tbToX.setText('-20000')
        self.ui.IDC_tbToY.setText('230000')

        self.__addRastersToGui()
        self.__addPolygonsToGui()

        for line_lyr in self.settings.mapData.lines.lines():
            self.ui.IDC_cbLineLayers.addItem(line_lyr.name, line_lyr)

        if self.settings.mapData.lines.count() < 1:
            self.ui.IDC_rbDigi.setChecked(True)
            self.ui.IDC_rbShapeLine.setEnabled(False)

        #Einstellungen fuer Linie zeichen
        self.action = QAction(QIcon(":/plugins/vogisprofiltoolmain/icons/icon.png"), "VoGIS-Profiltool", self.iface.mainWindow())
        self.action.setWhatsThis("VoGIS-Profiltool")
        self.canvas = self.iface.mapCanvas()
        self.tool = ProfiletoolMapTool(self.canvas, self.action)
        self.savedTool = self.canvas.mapTool()
        self.polygon = False
        self.rubberband = QgsRubberBand(self.canvas, self.polygon)
        if QGis.QGIS_VERSION_INT >= 10900:
            #self.rubberband.setBrushStyle()
            self.rubberband.setLineStyle(Qt.SolidLine)
            self.rubberband.setWidth(4.0)
            self.rubberband.setColor(QColor(0, 255, 0))
            #http://www.qgis.org/api/classQgsRubberBand.html#a6f7cdabfcf69b65dfc6c164ce2d01fab
        self.pointsToDraw = []
        self.dblclktemp = None
        self.drawnLine = None

    def accept(self):
        try:
            #QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", "ACCEPTED")

            #QgsMessageLog.logMessage('nodata: {0}'.format(self.settings.nodata_value), 'VoGis')
            self.settings.nodata_value = int(self.ui.IDC_tbNoDataExport.text())
            QgsMessageLog.logMessage('maindlg: nodata: {0}'.format(self.settings.nodata_value), 'VoGis')

            if self.settings.onlyHektoMode is True and self.settings.mapData.rasters.count() > 0:
                self.settings.onlyHektoMode = False

            if self.settings.onlyHektoMode is False:
                if self.settings.mapData.rasters.count() < 1:
                    #QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", u"Keine Raster vorhanden. Zum Hektometrieren Dialog neu öffnen.")
                    #return
                    retVal = QMessageBox.warning(self.iface.mainWindow(),
                                                 "VoGIS-Profiltool",
                                                 QApplication.translate('code', 'Keine Rasterebene vorhanden oder sichtbar! Nur hektometrieren?', None, QApplication.UnicodeUTF8),
                                                 QMessageBox.Yes | QMessageBox.No,
                                                 QMessageBox.Yes)
                    if retVal == QMessageBox.No:
                        return
                    else:
                        self.settings.onlyHektoMode = True
                        self.settings.createHekto = True

            if self.__getSettingsFromGui() is False:
                return

            if self.settings.onlyHektoMode is False:
                if len(self.settings.mapData.rasters.selectedRasters()) < 1:
                    #QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", "Kein Raster selektiert!")
                    #msg =
                    #QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", msg)
                    QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", QApplication.translate('code', 'Kein Raster selektiert!', None, QApplication.UnicodeUTF8))
                    return

            QgsMessageLog.logMessage('modeLine!=line: {0}'.format(self.settings.modeLine != enumModeLine.line), 'VoGis')
            QgsMessageLog.logMessage('customLine is None: {0}'.format(self.settings.mapData.customLine is None), 'VoGis')

            if self.settings.modeLine != enumModeLine.line and self.settings.mapData.customLine is None:
                QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", QApplication.translate('code', 'Keine Profillinie vorhanden!', None, QApplication.UnicodeUTF8))
                return

            if len(self.settings.mapData.polygons.selected_polygons()) > 0 and len(self.settings.mapData.rasters.selectedRasters()) > 1:
                raster_names = list(raster.name for raster in self.settings.mapData.rasters.selectedRasters())
                sel_raster, ok_clicked = QInputDialog.getItem(
                                                self.iface.mainWindow(),
                                                u'DHM?',
                                                u'Welches DHM soll zur Flächenverschneidung verwendet werden?',
                                                raster_names,
                                                0,
                                                False
                                                )
                if ok_clicked is False:
                    return
                self.settings.intersection_dhm_idx = raster_names.index(sel_raster)

            #self.rubberband.reset(self.polygon)
            #QDialog.accept(self)

            QApplication.setOverrideCursor(Qt.WaitCursor)

            create_profile = CreateProfile(self.iface, self.settings)
            thread = QThread(self)
            create_profile.moveToThread(thread)
            create_profile.finished.connect(self.profiles_finished)
            create_profile.error.connect(self.profiles_error)
            create_profile.progress.connect(self.profiles_progress)
            thread.started.connect(create_profile.create)
            thread.start(QThread.LowestPriority)
            self.thread = thread
            self.create_profile = create_profile
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        except:
            QApplication.restoreOverrideCursor()
            ex = u'{0}'.format(traceback.format_exc())
            msg = 'Unexpected ERROR:\n\n{0}'.format(ex[:2000])
            QMessageBox.critical(self.iface.mainWindow(), "VoGIS-Profiltool", msg)


    def profiles_finished(self, profiles, intersections):
        QApplication.restoreOverrideCursor()
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)
        #self.create_profile.deleteLater()
        self.thread.quit()
        self.thread.wait()
        #self.thread.deleteLater()

        #QGIS 2.0 http://gis.stackexchange.com/a/58754 http://gis.stackexchange.com/a/57090
        self.iface.mainWindow().statusBar().showMessage('VoGIS-Profiltool, {0} Profile'.format(len(profiles)))
        QgsMessageLog.logMessage(u'Profile Count: {0}'.format(len(profiles)), 'VoGis')

        if len(profiles) < 1:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", QApplication.translate('code', 'Es konnten keine Profile erstellt werden.', None, QApplication.UnicodeUTF8))
            return

        dlg = VoGISProfilToolPlotDialog(self.iface, self.settings, profiles, intersections)
        dlg.show()
        #result = self.dlg.exec_()
        dlg.exec_()


    def profiles_error(self, exception_string):
        QApplication.restoreOverrideCursor()
        QgsMessageLog.logMessage(u'Error during profile creation: {0}'.format(exception_string), 'VoGis')
        QMessageBox.critical(self.iface.mainWindow(), "VoGIS-Profiltool", exception_string)


    def profiles_progress(self, msg):
        self.iface.mainWindow().statusBar().showMessage(msg)
        self.ui.IDC_lblCreateStatus.setText(msg)
        #QgsMessageLog.logMessage(msg, 'VoGis')
        QApplication.processEvents()


    def reject(self):
        if not self.thread is None:
            if self.thread.isRunning():
                self.create_profile.abort()
                return

        self.rubberband.reset(self.polygon)
        QDialog.reject(self)


    def selectVisibleRasters(self):
        self.refreshRasterList()
        self.selectingVisibleRasters = True
        extCanvas = self.iface.mapCanvas().extent()
        #alle raster in den einstellunge deselektieren
        for r in self.settings.mapData.rasters.rasters():
            r.selected = False
        #alle raster in der ListView deselektieren
        for idx in xrange(self.ui.IDC_listRasters.count()):
            item = self.ui.IDC_listRasters.item(idx)
            item.setCheckState(Qt.Unchecked)
        #Raster im Extent selektieren
        for idx in xrange(self.ui.IDC_listRasters.count()):
            item = self.ui.IDC_listRasters.item(idx)
            if QGis.QGIS_VERSION_INT < 10900:
                raster = item.data(Qt.UserRole).toPyObject()
            else:
                raster = item.data(Qt.UserRole)
            for r in self.settings.mapData.rasters.rasters():
                if extCanvas.intersects(r.grid.extent()):
                    if r.id == raster.id:
                        r.selected = True
                        item.setCheckState(Qt.Checked)
        self.selectingVisibleRasters = False


    def lineLayerChanged(self, idx):
        if self.ui.IDC_rbShapeLine.isChecked() is False:
            self.ui.IDC_rbShapeLine.setChecked(True)
        if QGis.QGIS_VERSION_INT < 10900:
            lineLyr = (self.ui.IDC_cbLineLayers.itemData(self.ui.IDC_cbLineLayers.currentIndex()).toPyObject())
        else:
            lineLyr = (self.ui.IDC_cbLineLayers.itemData(self.ui.IDC_cbLineLayers.currentIndex()))
        lyr = lineLyr.line
        #QgsMessageLog.logMessage('{0}'.format(lyr.selectedFeatureCount()), 'VoGis')
        #QgsMessageLog.logMessage('{0}'.format(dir(lyr)), 'VoGis')
        if hasattr(lyr, 'selectedFeatureCount'):
            if(lyr.selectedFeatureCount() < 1):
                self.ui.IDC_chkOnlySelectedFeatures.setChecked(False)
            else:
                self.ui.IDC_chkOnlySelectedFeatures.setChecked(True)


    def valueChangedEquiDistance(self, val):
        if self.ui.IDC_rbEquiDistance.isChecked() is False:
            self.ui.IDC_rbEquiDistance.setChecked(True)


    def valueChangedVertexCount(self, val):
        if self.ui.IDC_rbVertexCount.isChecked() is False:
            self.ui.IDC_rbVertexCount.setChecked(True)


    def lvRasterItemChanged(self, item):
        if self.selectingVisibleRasters is True:
            return
        if item.checkState() == Qt.Checked:
            selected = True
        if item.checkState() == Qt.Unchecked:
            selected = False

        item_data = item.data(Qt.UserRole)
        if QGis.QGIS_VERSION_INT < 10900:
            raster_lyr = item_data.toPyObject()
        else:
            raster_lyr = item_data
        self.settings.mapData.rasters.getById(raster_lyr.id).selected = selected


    def lvPolygonItemChanged(self, item):
        if item.checkState() == Qt.Checked:
            selected = True
        if item.checkState() == Qt.Unchecked:
            selected = False

        item_data = item.data(Qt.UserRole)
        if QGis.QGIS_VERSION_INT < 10900:
            poly_lyr = item_data.toPyObject()
        else:
            poly_lyr = item_data
        self.settings.mapData.polygons.getById(poly_lyr.id).selected = selected


    def refreshRasterList(self):
        legend = self.iface.legendInterface()
        avail_lyrs = legend.layers()
        raster_coll = RasterCollection()

        for lyr in avail_lyrs:
            if legend.isLayerVisible(lyr):
                lyr_type = lyr.type()
                lyr_name = unicodedata.normalize('NFKD', unicode(lyr.name())).encode('ascii', 'ignore')
                if lyr_type == 1:
                    if lyr.bandCount() < 2:
                        new_raster = Raster(lyr.id(), lyr_name, lyr)
                        raster_coll.addRaster(new_raster)

        self.settings.mapData.rasters = raster_coll
        self.__addRastersToGui()

    def __addRastersToGui(self):
        self.ui.IDC_listRasters.clear()
        check = Qt.Unchecked
        if self.settings.mapData.rasters.count() == 1:
            check = Qt.Checked
            self.settings.mapData.rasters.rasters()[0].selected = True

        for raster_lyr in self.settings.mapData.rasters.rasters():
            item = QListWidgetItem(raster_lyr.name)
            item.setData(Qt.UserRole, raster_lyr)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(check)
            self.ui.IDC_listRasters.addItem(item)


    def __addPolygonsToGui(self):
        self.ui.IDC_listPolygons.clear()
        check = Qt.Unchecked
        for poly_lyr in self.settings.mapData.polygons.polygons():
            item = QListWidgetItem(poly_lyr.name)
            item.setData(Qt.UserRole, poly_lyr)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(check)
            self.ui.IDC_listPolygons.addItem(item)


    def drawLine(self):
        if self.ui.IDC_rbDigi.isChecked() is False:
            self.ui.IDC_rbDigi.setChecked(True)
        self.dblckltemp = None
        self.rubberband.reset(self.polygon)
        self.__cleanDigi()
        self.__activateDigiTool()
        self.canvas.setMapTool(self.tool)


    def __createDigiFeature(self, pnts):
        u = Util(self.iface)
        f = u.createQgLineFeature(pnts)
        self.settings.mapData.customLine = f


    def __lineFinished(self, position):
        mapPos = self.canvas.getCoordinateTransform().toMapCoordinates(position["x"], position["y"])
        newPoint = QgsPoint(mapPos.x(), mapPos.y())
        self.pointsToDraw.append(newPoint)
        #launch analyses
        self.iface.mainWindow().statusBar().showMessage(str(self.pointsToDraw))
        if len(self.pointsToDraw) < 2:
            self.__cleanDigi()
            self.pointsToDraw = []
            self.dblclktemp = newPoint
            self.drawnLine = None
            QMessageBox.warning(self, "VoGIS-Profiltool", QApplication.translate('code', 'Profillinie digitalisieren abgebrochen!', None, QApplication.UnicodeUTF8))
        self.drawnLine = self.__createDigiFeature(self.pointsToDraw)
        self.__cleanDigi()

        self.pointsToDraw = []
        self.dblclktemp = newPoint

    def __cleanDigi(self):
        self.pointsToDraw = []
        self.canvas.unsetMapTool(self.tool)
        self.canvas.setMapTool(self.savedTool)

    def __activateDigiTool(self):
        QObject.connect(self.tool, SIGNAL("moved"), self.__moved)
        QObject.connect(self.tool, SIGNAL("rightClicked"), self.__rightClicked)
        QObject.connect(self.tool, SIGNAL("leftClicked"), self.__leftClicked)
        QObject.connect(self.tool, SIGNAL("doubleClicked"), self.__doubleClicked)
        QObject.connect(self.tool, SIGNAL("deactivate"), self.__deactivateDigiTool)

    def __deactivateDigiTool(self):
        QObject.disconnect(self.tool, SIGNAL("moved"), self.__moved)
        QObject.disconnect(self.tool, SIGNAL("leftClicked"), self.__leftClicked)
        QObject.disconnect(self.tool, SIGNAL("rightClicked"), self.__rightClicked)
        QObject.disconnect(self.tool, SIGNAL("doubleClicked"), self.__doubleClicked)
        if QGis.QGIS_VERSION_INT < 10900:
            self.iface.mainWindow().statusBar().showMessage(QString(""))
        else:
            self.iface.mainWindow().statusBar().showMessage('')

    def __moved(self, position):
        if len(self.pointsToDraw) > 0:
            mapPos = self.canvas.getCoordinateTransform().toMapCoordinates(position["x"], position["y"])
            self.rubberband.reset(self.polygon)
            newPnt = QgsPoint(mapPos.x(), mapPos.y())
            if QGis.QGIS_VERSION_INT < 10900:
                for i in range(0, len(self.pointsToDraw)):
                    self.rubberband.addPoint(self.pointsToDraw[i])
                self.rubberband.addPoint(newPnt)
            else:
                pnts = self.pointsToDraw + [newPnt]
                self.rubberband.setToGeometry(QgsGeometry.fromPolyline(pnts),None)


    def __rightClicked(self, position):
        self.__lineFinished(position)

    def __leftClicked(self, position):
        mapPos = self.canvas.getCoordinateTransform().toMapCoordinates(position["x"], position["y"])
        newPoint = QgsPoint(mapPos.x(), mapPos.y())
        #if self.selectionmethod == 0:
        if newPoint == self.dblclktemp:
            self.dblclktemp = None
            return
        else:
            if len(self.pointsToDraw) == 0:
                self.rubberband.reset(self.polygon)
            self.pointsToDraw.append(newPoint)

    def __doubleClicked(self, position):
        pass

    #not in use right now
    def __lineCancel(self):
        pass

    def __getSettingsFromGui(self):
        self.settings.linesExplode = (self.ui.IDC_chkLinesExplode.checkState() == Qt.Checked)
        self.settings.linesMerge = (self.ui.IDC_chkLinesMerge.checkState() == Qt.Checked)
        self.settings.onlySelectedFeatures = (self.ui.IDC_chkOnlySelectedFeatures.checkState() == Qt.Checked)
        self.settings.equiDistance = self.ui.IDC_dblspinDistance.value()
        self.settings.vertexCnt = self.ui.IDC_dblspinVertexCnt.value()
        #self.settings.createHekto = (self.ui.IDC_chkCreateHekto.checkState() == Qt.Checked)
        self.settings.nodesAndVertices = (self.ui.IDC_chkNodesAndVertices.checkState() == Qt.Checked)

        if QGis.QGIS_VERSION_INT < 10900:
            self.settings.mapData.selectedLineLyr = (self.ui.IDC_cbLineLayers.itemData(
                                                     self.ui.IDC_cbLineLayers.currentIndex()
                                                     ).toPyObject()
                                                     )
        else:
            self.settings.mapData.selectedLineLyr = (self.ui.IDC_cbLineLayers.itemData(self.ui.IDC_cbLineLayers.currentIndex()))

        if self.settings.onlySelectedFeatures is True and self.settings.mapData.selectedLineLyr.line.selectedFeatureCount() < 1:
            QMessageBox.warning(self.iface.mainWindow(), "VoGIS-Profiltool", QApplication.translate('code', u'Der gewählte Layer hat keine selektierten Elemente.', None, QApplication.UnicodeUTF8))
            return False

        if self.ui.IDC_rbDigi.isChecked():
            self.settings.modeLine = enumModeLine.customLine
        elif self.ui.IDC_rbShapeLine.isChecked():
            self.settings.modeLine = enumModeLine.line
        else:
            #self.ui.IDC_rbStraigthLine
            self.settings.modeLine = enumModeLine.straightLine

        if self.ui.IDC_rbEquiDistance.isChecked():
            self.settings.modeVertices = enumModeVertices.equiDistant
        else:
            self.settings.modeVertices = enumModeVertices.vertexCnt

        if self.ui.IDC_rbStraigthLine.isChecked():
            ut = Util(self.iface)
            if ut.isFloat(self.ui.IDC_tbFromX.text(), QApplication.translate('code', 'Rechtswert von', None, QApplication.UnicodeUTF8)) is False:
                return False
            else:
                fromX = float(self.ui.IDC_tbFromX.text())
            if ut.isFloat(self.ui.IDC_tbFromY.text(), QApplication.translate('code', 'Hochwert von', None, QApplication.UnicodeUTF8)) is False:
                return False
            else:
                fromY = float(self.ui.IDC_tbFromY.text())
            if ut.isFloat(self.ui.IDC_tbToX.text(), QApplication.translate('code', 'Rechtswert nach', None, QApplication.UnicodeUTF8)) is False:
                return False
            else:
                toX = float(self.ui.IDC_tbToX.text())
            if ut.isFloat(self.ui.IDC_tbToY.text(), QApplication.translate('code', 'Hochwert nach', None, QApplication.UnicodeUTF8)) is False:
                return False
            else:
                toY = float(self.ui.IDC_tbToY.text())

            fromPnt = QgsPoint(fromX, fromY)
            toPnt = QgsPoint(toX, toY)

            self.settings.mapData.customLine = ut.createQgLineFeature([fromPnt, toPnt])

        return True
