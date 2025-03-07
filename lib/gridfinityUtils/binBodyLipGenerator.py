import adsk.core, adsk.fusion, traceback
import os
import math

from .const import BIN_CORNER_FILLET_RADIUS
from ...lib import fusion360utils as futil
from . import const, combineUtils, faceUtils, commonUtils, sketchUtils, extrudeUtils, baseGenerator, edgeUtils, filletUtils, geometryUtils
from .binBodyCutoutGenerator import createGridfinityBinBodyCutout
from .binBodyCutoutGeneratorInput import BinBodyCutoutGeneratorInput
from .baseGeneratorInput import BaseGeneratorInput
from .binBodyLipGeneratorInput import BinBodyLipGeneratorInput
from .binBodyTabGeneratorInput import BinBodyTabGeneratorInput
from .binBodyTabGenerator import createGridfinityBinBodyTab
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

def getInnerCutoutScoopFace(
    innerCutout: adsk.fusion.BRepBody
) -> tuple[adsk.fusion.BRepFace, adsk.fusion.BRepFace]:
    innerCutoutYNormalFaces = [face for face in innerCutout.faces if faceUtils.isYNormal(face)]
    scoopFace = min(innerCutoutYNormalFaces, key=lambda x: x.boundingBox.minPoint.y)
    oppositeFace = max(innerCutoutYNormalFaces, key=lambda x: x.boundingBox.minPoint.y)
    return (scoopFace, oppositeFace)

def createGridfinityBinBodyLip(
    input: BinBodyLipGeneratorInput,
    targetComponent: adsk.fusion.Component,
    ):

    lipPlaneInput: adsk.fusion.ConstructionPlaneInput = targetComponent.constructionPlanes.createInput()
    lipPlaneInput.setByOffset(
        targetComponent.xYConstructionPlane,
        adsk.core.ValueInput.createByReal(input.origin.z)
    )
    lipConstructionPlane = targetComponent.constructionPlanes.add(lipPlaneInput)

    actualLipBodyWidth = (input.baseWidth * input.binWidth) - input.xyTolerance * 2.0
    actualLipBodyLength = (input.baseLength * input.binLength) - input.xyTolerance * 2.0
    lipBodyHeight = const.BIN_LIP_EXTRA_HEIGHT
    features: adsk.fusion.Features = targetComponent.features

    lipBodyExtrude = extrudeUtils.createBox(
        actualLipBodyWidth,
        actualLipBodyLength,
        lipBodyHeight,
        targetComponent,
        lipConstructionPlane
    )
    lipBody = lipBodyExtrude.bodies.item(0)
    lipBody.name = 'lip body'

    bodiesToSubtract: list[adsk.fusion.BRepBody] = []

    # round corners
    filletUtils.filletEdgesByLength(
        lipBodyExtrude.faces,
        BIN_CORNER_FILLET_RADIUS,
        lipBodyHeight,
        targetComponent,
    )

    lipCutoutBodies: list[adsk.fusion.BRepBody] = []
    lipCutoutPlaneInput: adsk.fusion.ConstructionPlaneInput = targetComponent.constructionPlanes.createInput()
    lipCutoutPlaneInput.setByOffset(
        lipBodyExtrude.endFaces.item(0),
        adsk.core.ValueInput.createByReal(0)
    )
    lipCutoutConstructionPlane = targetComponent.constructionPlanes.add(lipCutoutPlaneInput)

    if input.hasLipNotches:
        lipCutoutInput = BaseGeneratorInput()
        lipCutoutInput.baseWidth = input.baseWidth
        lipCutoutInput.baseLength = input.baseLength
        lipCutoutInput.xyTolerance = input.xyTolerance
        lipCutoutInput.hasBottomChamfer = False
        lipCutout = baseGenerator.createBaseWithClearance(lipCutoutInput, targetComponent)
        lipCutout.name = "lip cutout"
        lipCutoutBodies.append(lipCutout)

        patternInputBodies = adsk.core.ObjectCollection.create()
        patternInputBodies.add(lipCutout)
        patternInput = features.rectangularPatternFeatures.createInput(patternInputBodies,
            targetComponent.xConstructionAxis,
            adsk.core.ValueInput.createByReal(input.binWidth),
            adsk.core.ValueInput.createByReal(input.baseWidth),
            adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
        patternInput.directionTwoEntity = targetComponent.yConstructionAxis
        patternInput.quantityTwo = adsk.core.ValueInput.createByReal(input.binLength)
        patternInput.distanceTwo = adsk.core.ValueInput.createByReal(input.baseLength)
        rectangularPattern = features.rectangularPatternFeatures.add(patternInput)
        lipCutoutBodies = lipCutoutBodies + list(rectangularPattern.bodies)

        lipMiddleCutoutOrigin = adsk.core.Point3D.create(
            input.origin.x + input.wallThickness,
            input.origin.y + input.wallThickness,
            input.origin.z,
        )
        lipMidCutout = extrudeUtils.createBoxAtPoint(
            actualLipBodyWidth - input.wallThickness * 2,
            actualLipBodyLength - input.wallThickness * 2,
            lipBodyHeight,
            targetComponent,
            lipMiddleCutoutOrigin,
        )
        filletUtils.filletEdgesByLength(
            lipMidCutout.faces,
            const.BIN_CORNER_FILLET_RADIUS - input.wallThickness,
            lipBodyHeight,
            targetComponent,
        )
        bodiesToSubtract.append(lipMidCutout.bodies.item(0))

    else:
        lipCutoutInput = BaseGeneratorInput()
        lipCutoutInput.baseWidth = input.baseWidth * input.binWidth
        lipCutoutInput.baseLength = input.baseLength * input.binLength
        lipCutoutInput.xyTolerance = input.xyTolerance
        lipCutoutInput.hasBottomChamfer = False
        lipCutout = baseGenerator.createBaseWithClearance(lipCutoutInput, targetComponent)
        lipCutout.name = "lip cutout"
        lipCutoutBodies.append(lipCutout)

    topChamferSketch: adsk.fusion.Sketch = targetComponent.sketches.add(lipCutoutConstructionPlane)
    sketchUtils.createRectangle(
        actualLipBodyWidth,
        actualLipBodyLength,
        adsk.core.Point3D.create(-actualLipBodyWidth / 2, -actualLipBodyLength / 2, 0),
        topChamferSketch,
    )
    topChamferNegativeVolume = extrudeUtils.simpleDistanceExtrude(
        topChamferSketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        const.BIN_LIP_TOP_RECESS_HEIGHT,
        adsk.fusion.ExtentDirections.NegativeExtentDirection,
        [],
        targetComponent,
    )
    bodiesToSubtract.append(topChamferNegativeVolume.bodies.item(0))
        
    # move up
    moveInput = features.moveFeatures.createInput2(commonUtils.objectCollectionFromList(lipCutoutBodies))
    moveInput.defineAsTranslateXYZ(
        adsk.core.ValueInput.createByReal(0),
        adsk.core.ValueInput.createByReal(0),
        adsk.core.ValueInput.createByReal(input.origin.z + const.BIN_BASE_HEIGHT),
        True
    )
    lipCutoutHeightAlignment = features.moveFeatures.add(moveInput)
    lipCutoutHeightAlignment.name = "move to the top"
    bodiesToSubtract = bodiesToSubtract + lipCutoutBodies

    combineUtils.cutBody(
        lipBody,
        commonUtils.objectCollectionFromList(bodiesToSubtract),
        targetComponent
    )

    return lipBody
