import QtQuick
import QtQuick3D

Item {
    id: root
    property url artworkSource: ""
    property real artworkAspect: 1.6
    property real cameraYaw: -18
    property real cameraPitch: -22
    property real cameraDistance: 950
    property real cameraPivotY: 48
    property real cameraOrbitTurns: 0
    property real lampBrightness: 2.4
    property real lampMotion: 0.65
    property string effectKind: "sand"
    property string rgbMode: "channels"
    property string effectDirection: "left"
    property real effectProgress: 0.0
    property int effectStageCount: 1
    property int effectOutlineStage: -1
    property var paintStageTargetU: []
    property var paintStageTargetV: []
    property var paintStageColors: []
    property real paintBrushWidth: 0.34
    property real paintDropSize: 0.024
    property real paintFallRatio: 0.30
    property var laserPathU: []
    property var laserPathV: []
    property var laserPathOn: []
    property real outputAspect: 16 / 9
    property bool showHud: true

    readonly property real artworkWidth: artworkAspect >= 1.0
        ? Math.min(360, 210 * artworkAspect) : 210 * artworkAspect
    readonly property real artworkDepth: artworkAspect >= 1.0
        ? artworkWidth / artworkAspect : 210
    readonly property real furnitureTopY: -20
    readonly property real artworkSurfaceY: -9
    readonly property real artworkCenterZ: -8
    readonly property real lampWave: Math.sin(effectProgress * Math.PI * 2)
    readonly property real lampCrossWave: Math.sin(effectProgress * Math.PI * 2 - 1.15)
    readonly property bool strictToolEffect: effectKind === "screenprint"
        || effectKind === "screenprint_laser"
        || effectKind === "paint_drop"
    readonly property real toolTimeline: strictToolEffect
        ? Math.min(effectStageCount - 0.0001, effectProgress * effectStageCount)
        : effectProgress
    readonly property int effectToolStage: strictToolEffect
        ? Math.floor(toolTimeline) : 0
    readonly property real effectToolLinearProgress: strictToolEffect
        ? toolTimeline - effectToolStage : effectProgress
    readonly property real effectToolProgress: strictToolEffect
        ? smootherstep(effectToolLinearProgress) : effectToolLinearProgress
    readonly property bool effectToolIsOutline: effectToolStage === effectOutlineStage
    readonly property real paintTargetU: effectToolStage < paintStageTargetU.length
        ? paintStageTargetU[effectToolStage] : 0.5
    readonly property real paintTargetV: effectToolStage < paintStageTargetV.length
        ? paintStageTargetV[effectToolStage] : 0.5
    readonly property color paintActiveColor: effectToolStage < paintStageColors.length
        ? paintStageColors[effectToolStage] : "#d94c4c"
    readonly property real laserPathPosition: effectToolProgress
        * Math.max(0, laserPathU.length - 1)
    readonly property int laserPathIndex: Math.min(
        Math.max(0, laserPathU.length - 2),
        Math.floor(laserPathPosition)
    )
    readonly property real laserPathMix: laserPathPosition - laserPathIndex
    readonly property real laserTargetU: laserPathU.length > 1
        ? laserPathU[laserPathIndex]
            + (laserPathU[laserPathIndex + 1] - laserPathU[laserPathIndex])
                * laserPathMix
        : effectToolProgress
    readonly property real laserTargetV: laserPathV.length > 1
        ? laserPathV[laserPathIndex]
            + (laserPathV[laserPathIndex + 1] - laserPathV[laserPathIndex])
                * laserPathMix
        : 0.5
    readonly property bool laserBeamOn: laserPathOn.length > 1
        ? laserPathOn[Math.min(laserPathIndex + 1, laserPathOn.length - 1)]
        : true
    readonly property bool satelliteView: cameraPitch < -48

    function smootherstep(value) {
        const t = Math.max(0, Math.min(1, value))
        return t * t * t * (t * (t * 6 - 15) + 10)
    }

    function wrapAngle(value) {
        return ((value + 180) % 360 + 360) % 360 - 180
    }

    function rgbWeight(channel) {
        if (rgbMode === "together")
            return effectProgress
        const start = channel * 0.25
        return Math.max(0, Math.min(1, (effectProgress - start) / 0.5))
    }

    Rectangle {
        anchors.fill: parent
        color: "#090a0c"
    }

    View3D {
        id: view
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#090a0c"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.VeryHigh
            temporalAAEnabled: true
            aoEnabled: true
            aoStrength: 76
            aoDistance: 14
            aoSoftness: 58
        }

        Node {
            id: scene

            Texture {
                id: walnutTexture
                source: "../materials/dark-walnut-v2.png"
                generateMipmaps: true
            }

            Node {
                id: cameraRig
                y: root.cameraPivotY
                eulerRotation.x: root.cameraPitch
                eulerRotation.y: root.cameraYaw
                    + root.cameraOrbitTurns * 360 * root.effectProgress
                PerspectiveCamera {
                    id: camera
                    z: root.cameraDistance - Math.sin(root.effectProgress * Math.PI) * 12
                    clipNear: 20
                    clipFar: 2800
                    fieldOfView: 39
                }
            }

            DirectionalLight {
                eulerRotation.x: -52
                eulerRotation.y: -34
                color: "#a9b4c2"
                ambientColor: "#1a2028"
                brightness: 0.3
            }
            PointLight {
                x: -330
                y: 115
                z: 390
                color: "#9fb2c8"
                ambientColor: "#11161c"
                brightness: 0.42
                constantFade: 1.0
                linearFade: 0.003
                quadraticFade: 0.000006
            }
            PointLight {
                x: 360
                y: 70
                z: 280
                color: "#c69b79"
                brightness: 0.22
                constantFade: 1.0
                linearFade: 0.004
                quadraticFade: 0.000008
            }

            // Empty architectural shell; no decorative props compete with the artwork.
            Model {
                id: floor
                y: -176
                source: "#Cube"
                scale: Qt.vector3d(13, 0.1, 10)
                materials: PrincipledMaterial {
                    baseColor: "#15161a"
                    roughness: 0.91
                    metalness: 0.03
                }
            }
            Model {
                id: backWall
                y: 245
                z: -430
                source: "#Cube"
                scale: Qt.vector3d(13, 8.4, 0.1)
                materials: PrincipledMaterial {
                    baseColor: "#1a1a1c"
                    roughness: 0.98
                }
            }
            Model {
                x: -650
                y: 245
                source: "#Cube"
                scale: Qt.vector3d(0.1, 8.4, 10)
                materials: PrincipledMaterial {
                    baseColor: "#101114"
                    roughness: 0.98
                }
            }
            Model {
                x: 650
                y: 245
                source: "#Cube"
                scale: Qt.vector3d(0.1, 8.4, 10)
                materials: PrincipledMaterial {
                    baseColor: "#101114"
                    roughness: 0.98
                }
            }

            // Contemporary walnut sideboard with drawers, brass details and tapered legs.
            Repeater3D {
                model: 4
                delegate: Model {
                    required property int index
                    x: index % 2 === 0 ? -225 : 225
                    y: -139
                    z: index < 2 ? -84 : 84
                    eulerRotation.z: index % 2 === 0 ? -2.2 : 2.2
                    eulerRotation.x: index < 2 ? 1.6 : -1.6
                    source: "#Cube"
                    scale: Qt.vector3d(0.17, 0.61, 0.17)
                    materials: PrincipledMaterial {
                        baseColor: "#171719"
                        metalness: 0.64
                        roughness: 0.3
                    }
                }
            }
            Model {
                id: sideboardBody
                y: -70
                source: "#Cube"
                scale: Qt.vector3d(5.4, 0.78, 2.35)
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    baseColorMap: walnutTexture
                    roughness: 0.48
                    metalness: 0.02
                }
            }
            Model {
                id: sideboardPlinth
                y: -108
                source: "#Cube"
                scale: Qt.vector3d(5.48, 0.055, 2.39)
                materials: PrincipledMaterial {
                    baseColor: "#151416"
                    metalness: 0.34
                    roughness: 0.38
                }
            }
            Model {
                id: sideboardTop
                y: -26
                source: "#Cube"
                scale: Qt.vector3d(5.65, 0.13, 2.52)
                materials: PrincipledMaterial {
                    baseColor: "#29282a"
                    metalness: 0.12
                    roughness: 0.39
                }
            }
            Repeater3D {
                model: 3
                delegate: Model {
                    required property int index
                    x: (index - 1) * 174
                    y: -66
                    z: 120
                    source: "#Cube"
                    scale: Qt.vector3d(1.66, 0.28, 0.035)
                    materials: PrincipledMaterial {
                        baseColor: index === 1 ? "#e2d6cb" : "#ffffff"
                        baseColorMap: walnutTexture
                        roughness: 0.43
                    }
                }
            }
            Repeater3D {
                model: 3
                delegate: Model {
                    required property int index
                    x: (index - 1) * 174
                    y: -63
                    z: 126
                    eulerRotation.z: 90
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.045, 0.28, 0.045)
                    materials: PrincipledMaterial {
                        baseColor: "#b88a52"
                        metalness: 0.8
                        roughness: 0.22
                    }
                }
            }

            // The artwork lies flat like a precious object, with a restrained contact shadow.
            Node {
                id: artworkDeck
                z: root.artworkCenterZ
                eulerRotation.y: -3

                Model {
                    id: artworkContactShadow
                    x: -root.lampWave * root.lampMotion * 7
                    y: root.furnitureTopY + 0.9
                    z: -root.lampCrossWave * root.lampMotion * 4
                    eulerRotation.x: -90
                    source: "#Rectangle"
                    scale: Qt.vector3d(
                        (root.artworkWidth + 28) / 100,
                        (root.artworkDepth + 24) / 100,
                        1
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#050506"
                        opacity: 0.2
                        roughness: 1.0
                    }
                }
                Model {
                    id: horizontalArtworkFrame
                    y: -14
                    source: "#Cube"
                    scale: Qt.vector3d(
                        (root.artworkWidth + 18) / 100,
                        0.075,
                        (root.artworkDepth + 18) / 100
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#111114"
                        metalness: 0.38
                        roughness: 0.25
                    }
                }
                Model {
                    id: horizontalArtwork
                    y: root.artworkSurfaceY
                    eulerRotation.x: -90
                    source: "#Rectangle"
                    scale: Qt.vector3d(
                        root.artworkWidth / 100,
                        root.artworkDepth / 100,
                        1
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#ffffff"
                        roughness: 0.47
                        baseColorMap: Texture {
                            sourceItem: Image {
                                source: root.artworkSource
                                cache: false
                                asynchronous: false
                            }
                            generateMipmaps: true
                        }
                    }
                }
            }

            // Every grain comes from a real analyzed pixel and settles at its 2D time.
            Repeater3D {
                model: sandParticleModel
                delegate: Model {
                    required property real targetU
                    required property real targetV
                    required property color particleColor
                    required property real birthProgress
                    required property real settleProgress
                    required property real driftX
                    required property real driftZ
                    required property real particleSize
                    readonly property real travel: Math.max(0, Math.min(1,
                        (root.effectProgress - birthProgress)
                        / Math.max(0.0001, settleProgress - birthProgress)))
                    readonly property real fall: travel * travel
                    visible: root.effectKind === "sand"
                        && travel > 0.0 && travel < 1.0
                    x: (targetU - 0.5) * root.artworkWidth
                        + driftX * (1 - fall)
                        + Math.sin(targetU * 91 + targetV * 57 + travel * 6.28)
                        * (1 - fall) * 3.2
                    y: root.artworkSurfaceY + 245 * (1 - fall)
                    z: root.artworkCenterZ + (targetV - 0.5) * root.artworkDepth
                        + driftZ * (1 - fall)
                    source: "#Sphere"
                    scale: Qt.vector3d(
                        particleSize * 1.55 / 100,
                        particleSize * 3.8 / 100,
                        particleSize * 1.55 / 100
                    )
                    materials: PrincipledMaterial {
                        baseColor: particleColor
                        opacity: 0.82
                        roughness: 0.84
                    }
                }
            }

            // The tool shares the exact transform and quintic timing of the artwork deck.
            Node {
                id: effectToolDeck
                readonly property bool isHalo: root.effectKind === "vertical_halo"
                readonly property bool isScreen: root.effectKind === "screenprint"
                    || (root.effectKind === "screenprint_laser"
                        && !root.effectToolIsOutline)
                readonly property bool isLaser: root.effectKind === "contour_laser"
                    || (root.effectKind === "screenprint_laser"
                        && root.effectToolIsOutline)
                readonly property real halfWidth: isLaser ? 1.4 : (isScreen ? 8 : 5)
                readonly property real travelProgress: isHalo
                    && root.effectDirection === "right"
                    ? 1.0 - root.effectToolProgress : root.effectToolProgress
                visible: (isHalo || isScreen || isLaser)
                    && root.effectToolProgress > 0.005
                    && root.effectToolProgress < 0.995
                z: isLaser
                    ? root.artworkCenterZ
                        + (root.laserTargetV - 0.5) * root.artworkDepth
                    : root.artworkCenterZ
                eulerRotation.y: -3
                x: isLaser
                    ? -root.artworkWidth / 2 + root.artworkWidth * root.laserTargetU
                    : Math.max(
                        -root.artworkWidth / 2 + halfWidth,
                        Math.min(
                            root.artworkWidth / 2 - halfWidth,
                            -root.artworkWidth / 2
                                + root.artworkWidth * effectToolDeck.travelProgress
                        )
                    )

                Model {
                    id: effectToolCore
                    y: root.artworkSurfaceY + (effectToolDeck.isLaser ? 24 : 7.0)
                    source: effectToolDeck.isLaser ? "#Cylinder" : "#Cube"
                    scale: Qt.vector3d(
                        effectToolDeck.isLaser ? 0.10
                            : (effectToolDeck.isScreen ? 0.14 : 0.10),
                        effectToolDeck.isLaser ? 0.12 : 0.028,
                        effectToolDeck.isLaser ? 0.10 : root.artworkDepth / 100
                    )
                    materials: PrincipledMaterial {
                        baseColor: effectToolDeck.isLaser ? "#3d434c"
                            : (effectToolDeck.isScreen ? "#fff0d7" : "#fff7e9")
                        emissiveFactor: effectToolDeck.isLaser
                            ? Qt.vector3d(0.08, 0.06, 0.04)
                            : Qt.vector3d(0.82, 0.58, 0.30)
                        opacity: effectToolDeck.isLaser ? 0.96 : 0.88
                        roughness: 0.10
                    }
                }
                Model {
                    id: effectLaserCollar
                    visible: effectToolDeck.isLaser
                    y: root.artworkSurfaceY + 15.5
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.106, 0.018, 0.106)
                    materials: PrincipledMaterial {
                        baseColor: "#c13a22"
                        emissiveFactor: Qt.vector3d(0.22, 0.025, 0.01)
                        metalness: 0.66
                        roughness: 0.17
                    }
                }
                Model {
                    id: effectToolAura
                    visible: !effectToolDeck.isLaser || root.laserBeamOn
                    y: root.artworkSurfaceY + 1.4
                    source: "#Cube"
                    scale: Qt.vector3d(
                        effectToolDeck.isLaser ? 0.055
                            : (effectToolDeck.isScreen ? 0.34 : 0.24),
                        0.006,
                        effectToolDeck.isLaser ? 0.055 : (root.artworkDepth + 12) / 100
                    )
                    materials: PrincipledMaterial {
                        baseColor: effectToolDeck.isLaser ? "#ff5b24" : "#ffd9a8"
                        emissiveFactor: effectToolDeck.isLaser
                            ? Qt.vector3d(1.0, 0.18, 0.035)
                            : Qt.vector3d(0.34, 0.22, 0.11)
                        opacity: effectToolDeck.isLaser ? 0.24 : 0.16
                        roughness: 0.22
                    }
                }
                Repeater3D {
                    model: 2
                    delegate: Model {
                        required property int index
                        visible: effectToolDeck.isScreen
                        y: root.artworkSurfaceY + 14
                        z: (index === 0 ? -1 : 1) * (root.artworkDepth / 2 + 7)
                        source: "#Cube"
                        scale: Qt.vector3d(0.22, 0.09, 0.15)
                        materials: PrincipledMaterial {
                            baseColor: "#f2b66f"
                            metalness: 0.58
                            roughness: 0.20
                            emissiveFactor: Qt.vector3d(0.48, 0.26, 0.08)
                        }
                    }
                }
                Model {
                    id: effectLaserEmitter
                    visible: effectToolDeck.isLaser && root.laserBeamOn
                    y: root.artworkSurfaceY + 12
                    z: 0
                    source: "#Sphere"
                    scale: Qt.vector3d(0.052, 0.052, 0.052)
                    materials: PrincipledMaterial {
                        baseColor: "#ffcf9b"
                        emissiveFactor: Qt.vector3d(1.0, 0.24, 0.04)
                        metalness: 0.18
                        roughness: 0.12
                    }
                }
                Model {
                    visible: effectToolDeck.isLaser && root.laserBeamOn
                    y: root.artworkSurfaceY + 6.5
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.012, 0.105, 0.012)
                    materials: PrincipledMaterial {
                        baseColor: "#fff0c2"
                        emissiveFactor: Qt.vector3d(1.0, 0.18, 0.025)
                        opacity: 0.94
                        roughness: 0.05
                    }
                }
                Model {
                    visible: effectToolDeck.isLaser && root.laserBeamOn
                    y: root.artworkSurfaceY + 1.1
                    source: "#Sphere"
                    scale: Qt.vector3d(0.07, 0.012, 0.07)
                    materials: PrincipledMaterial {
                        baseColor: "#ff6a24"
                        emissiveFactor: Qt.vector3d(1.0, 0.16, 0.02)
                        opacity: 0.62
                        roughness: 0.18
                    }
                }
                SpotLight {
                    visible: !effectToolDeck.isLaser || root.laserBeamOn
                    y: root.artworkSurfaceY + 54
                    eulerRotation.x: -90
                    color: effectToolDeck.isLaser ? "#ff5a20" : "#ffd0a0"
                    brightness: effectToolDeck.isLaser ? 1.5 : 0.82
                    coneAngle: effectToolDeck.isLaser ? 30 : 42
                    innerConeAngle: effectToolDeck.isLaser ? 14 : 25
                    castsShadow: false
                    quadraticFade: 0.00009
                }
            }

            // XY cutter gantry: fixed rails, moving crossbar and path-following head.
            Node {
                id: laserGantry
                visible: effectToolDeck.visible && effectToolDeck.isLaser
                z: root.artworkCenterZ
                eulerRotation.y: -3

                Repeater3D {
                    model: 2
                    delegate: Model {
                        required property int index
                        x: (index === 0 ? -1 : 1) * (root.artworkWidth / 2 + 9)
                        y: root.artworkSurfaceY + 38
                        source: "#Cube"
                        scale: Qt.vector3d(0.035, 0.035, root.artworkDepth / 100)
                        materials: PrincipledMaterial {
                            baseColor: "#343a43"
                            metalness: 0.82
                            roughness: 0.20
                        }
                    }
                }
                Model {
                    y: root.artworkSurfaceY + 42
                    z: (root.laserTargetV - 0.5) * root.artworkDepth
                    source: "#Cube"
                    scale: Qt.vector3d(root.artworkWidth / 100, 0.042, 0.042)
                    materials: PrincipledMaterial {
                        baseColor: "#555f6c"
                        metalness: 0.88
                        roughness: 0.16
                    }
                }
            }


            // A real oversized flat brush drops the analyzed layer color onto its true zone.
            Node {
                id: paintBrushDeck
                visible: root.effectKind === "paint_drop"
                    && root.effectProgress > 0.005
                    && root.effectProgress < 0.995
                x: -root.artworkWidth / 2 + root.artworkWidth * root.paintTargetU
                z: root.artworkCenterZ
                eulerRotation.y: -3
                readonly property real targetZ: (root.paintTargetV - 0.5)
                    * root.artworkDepth
                readonly property real fallProgress: Math.min(
                    1.0,
                    root.effectToolLinearProgress / Math.max(root.paintFallRatio, 0.001)
                )
                readonly property real dropScale: Math.max(
                    0.045,
                    Math.min(root.artworkWidth, root.artworkDepth)
                        * root.paintDropSize / 100.0
                )

                Model {
                    y: root.artworkSurfaceY + 132
                    z: paintBrushDeck.targetZ
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.105, 1.02, 0.105)
                    materials: PrincipledMaterial {
                        baseColor: "#7b4328"
                        roughness: 0.38
                        metalness: 0.05
                    }
                }
                Model {
                    y: root.artworkSurfaceY + 72
                    z: paintBrushDeck.targetZ
                    source: "#Cube"
                    scale: Qt.vector3d(
                        root.artworkWidth * root.paintBrushWidth / 100,
                        0.16,
                        0.20
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#d3b27a"
                        metalness: 0.62
                        roughness: 0.24
                    }
                }
                Model {
                    y: root.artworkSurfaceY + 43
                    z: paintBrushDeck.targetZ + 1.6
                    source: "#Cube"
                    scale: Qt.vector3d(
                        root.artworkWidth * root.paintBrushWidth * 0.84 / 100,
                        0.235,
                        0.115
                    )
                    materials: PrincipledMaterial {
                        baseColor: Qt.darker(root.paintActiveColor, 2.15)
                        roughness: 0.98
                    }
                }
                Repeater3D {
                    model: 13
                    delegate: Model {
                        required property int index
                        x: (index - 6) * root.artworkWidth
                            * root.paintBrushWidth * 0.061
                        y: root.artworkSurfaceY + 42
                            - Math.abs(index - 6) * 0.42
                            + Math.sin(index * 1.7) * 0.9
                        z: paintBrushDeck.targetZ + Math.sin(index * 2.1) * 1.3
                        source: "#Cube"
                        scale: Qt.vector3d(
                            0.024,
                            0.255 + Math.sin(index * 1.3) * 0.018,
                            0.145
                        )
                        materials: PrincipledMaterial {
                            baseColor: Qt.darker(root.paintActiveColor, 1.72)
                            roughness: 0.96
                        }
                    }
                }
                Model {
                    y: root.artworkSurfaceY + 28
                    z: paintBrushDeck.targetZ
                    source: "#Cube"
                    scale: Qt.vector3d(
                        root.artworkWidth * root.paintBrushWidth * 0.82 / 100,
                        0.035,
                        0.17
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        roughness: 0.16
                        clearcoatAmount: 0.64
                        clearcoatRoughnessAmount: 0.10
                    }
                }
                Model {
                    visible: root.effectToolLinearProgress < root.paintFallRatio
                    y: root.artworkSurfaceY + 3
                        + 22 * (1.0 - root.smootherstep(paintBrushDeck.fallProgress))
                    z: paintBrushDeck.targetZ
                    source: "#Sphere"
                    scale: Qt.vector3d(
                        paintBrushDeck.dropScale,
                        paintBrushDeck.dropScale * 1.45,
                        paintBrushDeck.dropScale
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        roughness: 0.12
                        clearcoatAmount: 0.72
                        clearcoatRoughnessAmount: 0.08
                    }
                }
                Model {
                    visible: root.effectToolLinearProgress >= root.paintFallRatio
                        && root.effectToolLinearProgress < root.paintFallRatio + 0.24
                    readonly property real bloom: Math.max(
                        0.0,
                        (root.effectToolLinearProgress - root.paintFallRatio) / 0.24
                    )
                    y: root.artworkSurfaceY + 1.2
                    z: paintBrushDeck.targetZ
                    source: "#Cylinder"
                    scale: Qt.vector3d(
                        0.05 + bloom * 0.34,
                        0.006,
                        0.05 + bloom * 0.34
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        opacity: Math.max(0.0, 0.52 * (1.0 - bloom))
                        roughness: 0.24
                    }
                }
                PointLight {
                    y: root.artworkSurfaceY + 48
                    z: paintBrushDeck.targetZ
                    color: root.paintActiveColor
                    brightness: 0.22
                    quadraticFade: 0.00034
                }
            }


            // Wave fronts skim a few millimetres above the horizontal artwork.
            Model {
                readonly property bool horizontalFront: root.effectDirection === "left"
                    || root.effectDirection === "right"
                visible: root.effectKind === "wave"
                    && root.effectProgress > 0.01
                    && root.effectProgress < 0.99
                x: horizontalFront
                    ? (root.effectDirection === "right" ? 1 : -1)
                        * root.artworkWidth * (0.5 - root.effectProgress) : 0
                y: root.artworkSurfaceY + 4
                z: horizontalFront
                    ? root.artworkCenterZ
                    : root.artworkCenterZ - root.artworkDepth / 2
                        + root.artworkDepth * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress)
                eulerRotation.y: root.effectDirection === "diagonal" ? -24 : 0
                source: root.effectDirection === "radial" ? "#Cylinder" : "#Cube"
                scale: root.effectDirection === "radial"
                    ? Qt.vector3d(
                        0.18 + root.effectProgress * 1.35,
                        0.012,
                        0.18 + root.effectProgress * 1.35
                    )
                    : horizontalFront
                        ? Qt.vector3d(0.024, 0.024, root.artworkDepth / 100)
                        : Qt.vector3d(root.artworkWidth / 100, 0.024, 0.024)
                materials: PrincipledMaterial {
                    baseColor: "#79c4ec"
                    emissiveFactor: Qt.vector3d(0.11, 0.31, 0.5)
                    opacity: root.effectDirection === "radial" ? 0.2 : 0.58
                    roughness: 0.2
                }
            }
            Model {
                readonly property bool horizontalFront: root.effectDirection === "left"
                    || root.effectDirection === "right"
                visible: root.effectKind === "wave"
                    && root.effectDirection !== "radial"
                    && root.effectProgress > 0.01
                    && root.effectProgress < 0.99
                x: horizontalFront
                    ? (root.effectDirection === "right" ? 1 : -1)
                        * root.artworkWidth * (0.5 - root.effectProgress) : 0
                y: root.artworkSurfaceY + 7
                z: horizontalFront
                    ? root.artworkCenterZ + Math.sin(root.effectProgress * 14) * 5
                    : root.artworkCenterZ - root.artworkDepth / 2
                        + root.artworkDepth * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress)
                eulerRotation.y: root.effectDirection === "diagonal" ? -24 : 0
                source: "#Cube"
                scale: horizontalFront
                    ? Qt.vector3d(0.011, 0.018, root.artworkDepth / 105)
                    : Qt.vector3d(root.artworkWidth / 105, 0.018, 0.011)
                materials: PrincipledMaterial {
                    baseColor: "#c5e9f8"
                    emissiveFactor: Qt.vector3d(0.18, 0.34, 0.5)
                    opacity: 0.34
                    roughness: 0.18
                }
            }

            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: -170
                y: 75
                z: root.artworkCenterZ
                color: "#ff3348"
                brightness: root.rgbWeight(0) * 0.9
                quadraticFade: 0.000014
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 0
                y: 100
                z: root.artworkCenterZ - 45
                color: "#36df77"
                brightness: root.rgbWeight(1) * 0.82
                quadraticFade: 0.000014
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 170
                y: 70
                z: root.artworkCenterZ + 20
                color: "#4385ff"
                brightness: root.rgbWeight(2) * 0.92
                quadraticFade: 0.000014
            }

            // The pendant and its light share one slow, deterministic physical swing.
            Node {
                id: hangingLampRig
                x: root.lampWave * root.lampMotion * 52
                y: 445
                z: -16 + root.lampCrossWave * root.lampMotion * 20
                eulerRotation.z: root.lampWave * root.lampMotion * 5.0
                eulerRotation.x: root.lampCrossWave * root.lampMotion * 2.4

                Model {
                    id: overheadLampCable
                    visible: !root.satelliteView
                    y: -86
                    source: "#Cylinder"
                    scale: Qt.vector3d(0.024, 1.72, 0.024)
                    materials: PrincipledMaterial {
                        baseColor: "#08090a"
                        metalness: 0.68
                        roughness: 0.23
                    }
                }
                Model {
                    id: overheadLamp
                    visible: !root.satelliteView
                    y: -182
                    source: "#Cone"
                    scale: Qt.vector3d(1.46, 0.66, 1.46)
                    materials: PrincipledMaterial {
                        baseColor: "#17110d"
                        metalness: 0.62
                        roughness: 0.29
                    }
                }
                Model {
                    visible: !root.satelliteView
                    y: -214
                    source: "#Cylinder"
                    scale: Qt.vector3d(1.46, 0.035, 1.46)
                    materials: PrincipledMaterial {
                        baseColor: "#c38b56"
                        emissiveFactor: Qt.vector3d(0.17, 0.1, 0.05)
                        roughness: 0.46
                    }
                }
                Model {
                    visible: !root.satelliteView
                    y: -223
                    source: "#Sphere"
                    scale: Qt.vector3d(0.16, 0.16, 0.16)
                    materials: PrincipledMaterial {
                        baseColor: "#ffd8a4"
                        emissiveFactor: Qt.vector3d(0.75, 0.5, 0.25)
                        roughness: 0.24
                    }
                }
                SpotLight {
                    y: -230
                    eulerRotation.x: -90
                    color: "#ffd1a0"
                    brightness: root.lampBrightness * 3.45
                    coneAngle: 64
                    innerConeAngle: 38
                    castsShadow: true
                }
                PointLight {
                    y: -225
                    color: "#ffc58c"
                    ambientColor: "#20150d"
                    brightness: root.lampBrightness * 0.52
                    constantFade: 1.0
                    linearFade: 0.004
                    quadraticFade: 0.000014
                }
            }
        }
    }

    Rectangle {
        id: effectActBadge
        visible: root.showHud
            && (root.effectKind === "vertical_halo"
                || root.effectKind === "screenprint"
                || root.effectKind === "contour_laser"
                || root.effectKind === "screenprint_laser"
                || root.effectKind === "paint_drop")
            && root.effectProgress > 0.005
            && root.effectProgress < 0.995
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 18
        radius: 8
        color: "#d0161b25"
        border.color: root.effectKind === "paint_drop"
            ? root.paintActiveColor
            : (root.effectToolIsOutline ? "#ff6a32" : "#c99a67")
        border.width: 1
        width: effectActText.implicitWidth + 26
        height: 34

        Text {
            id: effectActText
            anchors.centerIn: parent
            color: root.effectToolIsOutline ? "#ffd1b6" : "#ffe0b9"
            text: root.effectKind === "paint_drop"
                ? "COUCHE " + (root.effectToolStage + 1) + "/"
                    + root.effectStageCount + " · "
                    + (root.effectToolLinearProgress < root.paintFallRatio
                        ? "GOUTTE EN CHUTE" : "PEINTURE EN EXPANSION")
                : root.effectKind === "screenprint_laser"
                ? (root.effectToolIsOutline
                    ? "ACTE 2 · LASER DES CONTOURS NOIRS"
                    : "ACTE 1 · SÉRIGRAPHIE COULEUR "
                        + (root.effectToolStage + 1) + "/"
                        + Math.max(1, root.effectStageCount - 1))
                : root.effectKind === "screenprint"
                    ? "SÉRIGRAPHIE · COUCHE " + (root.effectToolStage + 1)
                    : root.effectKind === "contour_laser"
                        ? "DÉCOUPEUSE LASER · ÉCRITURE DES FORMES"
                        : (root.effectDirection === "right"
                            ? "HALO VERTICAL · RÉVÉLATION DROITE → GAUCHE"
                            : "HALO VERTICAL · RÉVÉLATION GAUCHE → DROITE")
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 0.55
        }
    }

    MouseArea {
        id: orbitArea
        anchors.fill: parent
        enabled: root.showHud
        acceptedButtons: Qt.LeftButton
        property real lastX: 0
        property real lastY: 0
        onPressed: function(mouse) {
            lastX = mouse.x
            lastY = mouse.y
        }
        onPositionChanged: function(mouse) {
            if (!pressed)
                return
            root.cameraYaw = root.wrapAngle(
                root.cameraYaw + (mouse.x - lastX) * 0.28)
            root.cameraPitch = Math.max(-82, Math.min(5,
                root.cameraPitch + (mouse.y - lastY) * 0.2))
            lastX = mouse.x
            lastY = mouse.y
        }
        onWheel: function(wheel) {
            root.cameraDistance = Math.max(420, Math.min(1400,
                root.cameraDistance - wheel.angleDelta.y * 0.45))
            wheel.accepted = true
        }
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
    }

    Item {
        id: exportGuide
        visible: root.showHud
        anchors.centerIn: parent
        width: Math.min(parent.width - 38, (parent.height - 38) * root.outputAspect)
        height: width / root.outputAspect

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: "#e8edff"
            border.width: 2
            radius: 3
        }
        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: 8
            color: "#c7161b25"
            radius: 5
            width: frameText.implicitWidth + 14
            height: frameText.implicitHeight + 8
            Text {
                id: frameText
                anchors.centerIn: parent
                text: "CADRE EXPORT"
                color: "#f2f5ff"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 0.7
            }
        }
    }

    Rectangle {
        visible: root.showHud
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 16
        radius: 8
        color: "#b8161b25"
        width: instruction.implicitWidth + 24
        height: instruction.implicitHeight + 14
        Text {
            id: instruction
            anchors.centerIn: parent
            text: "GLISSER · ORBITER     MOLETTE · DISTANCE"
            color: "#eef2ff"
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 0.8
        }
    }
}
