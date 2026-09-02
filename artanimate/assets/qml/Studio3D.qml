import QtQuick
import QtQuick3D

Item {
    id: root
    property url artworkSource: ""
    property real artworkAspect: 1.6
    property real cameraYaw: 0
    property real cameraPitch: -78
    property real cameraRoll: 0
    property real cameraDistance: 560
    property real cameraPivotY: -8
    property real cameraX: 0
    property real cameraZ: 0
    property real cameraFieldOfView: 39
    property real cameraOrbitTurns: 0
    property string cameraMotion: "flyover"
    property real cameraMotionStrength: 1.0
    property real cameraMatchWeight: 0
    property real cameraMatchX: 0
    property real cameraMatchY: -8
    property real cameraMatchZ: 0
    property real cameraMatchPitch: -78
    property real cameraMatchYaw: 0
    property real cameraMatchRoll: 0
    property real cameraMatchDistance: 560
    property real cameraMatchFieldOfView: 39
    property bool cameraResolvedPoseEnabled: false
    property real cameraResolvedX: 0
    property real cameraResolvedY: -8
    property real cameraResolvedZ: 0
    property real cameraResolvedPitch: -78
    property real cameraResolvedYaw: 0
    property real cameraResolvedRoll: 0
    property real cameraResolvedDistance: 560
    property real cameraResolvedFieldOfView: 39
    property real lampBrightness: 2.4
    property real lampMotion: 0.65
    property string artworkColorMode: 'faithful'
    property string artworkTextureColorSpace: 'srgb'
    property real artworkExposure: 1.0
    property string artworkToneMapping: 'linear'
    property string effectKind: "sand"
    property string rgbMode: "channels"
    property string effectDirection: "left"
    property real effectProgress: 0.0
    property int effectStageCount: 1
    property int effectOutlineStage: -1
    property var paintStageTargetU: []
    property var paintStageTargetV: []
    property var paintStageColors: []
    property real paintDropSize: 0.12
    property real paintFallRatio: 0.38
    property real laserCursorU: 0.5
    property real laserCursorV: 0.5
    property bool laserCursorOn: false
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
    readonly property bool satelliteView: cameraPitch < -48

    function smootherstep(value) {
        const t = Math.max(0, Math.min(1, value))
        return t * t * t * (t * (t * 6 - 15) + 10)
    }

    function lerp(first, second, weight) {
        return first + (second - first) * weight
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
            // Fixed by ArtworkColorPolicy for identical preview, headless and export.
            tonemapMode: SceneEnvironment.TonemapModeLinear
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
                readonly property bool flyover: root.cameraMotion === "flyover"
                readonly property bool topDrift: root.cameraMotion === "top_drift"
                readonly property real flightProgress: root.smootherstep(
                    root.effectProgress / 0.62)
                readonly property real settleProgress: root.smootherstep(
                    (root.effectProgress - 0.58) / 0.32)
                readonly property real flyoverWeight: flyover
                    ? root.cameraMotionStrength * (1 - settleProgress) : 0
                readonly property real driftEnvelope: topDrift
                    ? root.cameraMotionStrength * Math.sin(root.effectProgress * Math.PI)
                    : 0
                readonly property real railX: root.artworkWidth
                    * (-0.32 + 0.62 * flightProgress
                        + Math.sin(flightProgress * Math.PI * 2) * 0.055)
                readonly property real railZ: root.artworkCenterZ
                    + root.artworkDepth * (0.30 - 0.52 * flightProgress)
                readonly property real railPitch: -25
                    - Math.sin(flightProgress * Math.PI) * 4
                readonly property real railYaw: -8
                    + Math.sin(flightProgress * Math.PI * 1.15) * 13
                readonly property real railDistance: 330
                    - Math.sin(flightProgress * Math.PI) * 15
                readonly property real fitTangent: Math.tan(
                    root.cameraFieldOfView * Math.PI / 360)
                readonly property real fitDistance: Math.max(
                    root.cameraDistance,
                    root.artworkWidth * 1.08
                        / (2 * fitTangent * Math.max(0.2, root.outputAspect)),
                    root.artworkDepth * 1.08 / (2 * fitTangent))
                readonly property real baseDistance: fitDistance
                    + flyoverWeight * (railDistance - fitDistance)
                    - driftEnvelope * 26
                readonly property real baseX: root.cameraX + railX * flyoverWeight
                    + root.artworkWidth * 0.075
                        * Math.sin(root.effectProgress * Math.PI * 2) * driftEnvelope
                readonly property real baseY: root.cameraPivotY
                    + flyoverWeight * (root.artworkSurfaceY + 3 - root.cameraPivotY)
                readonly property real baseZ: root.cameraZ + railZ * flyoverWeight
                    + root.artworkDepth * 0.055
                        * Math.cos(root.effectProgress * Math.PI * 2) * driftEnvelope
                readonly property real basePitch: root.cameraPitch
                    + flyoverWeight * (railPitch - root.cameraPitch)
                    - driftEnvelope * 2.5
                        * Math.sin(root.effectProgress * Math.PI * 2)
                readonly property real baseYaw: root.cameraYaw
                    + flyoverWeight * (railYaw - root.cameraYaw)
                    + driftEnvelope * 4
                        * Math.sin(root.effectProgress * Math.PI * 2)
                    + root.cameraOrbitTurns * 360 * root.effectProgress
                readonly property real baseFieldOfView: root.cameraFieldOfView
                    + flyoverWeight * 7 + driftEnvelope * 1.5
                readonly property real animatedDistance:
                    root.cameraResolvedPoseEnabled
                        ? root.cameraResolvedDistance
                        : root.lerp(baseDistance, root.cameraMatchDistance, root.cameraMatchWeight)
                x: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedX
                    : root.lerp(baseX, root.cameraMatchX, root.cameraMatchWeight)
                y: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedY
                    : root.lerp(baseY, root.cameraMatchY, root.cameraMatchWeight)
                z: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedZ
                    : root.lerp(baseZ, root.cameraMatchZ, root.cameraMatchWeight)
                eulerRotation.x: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedPitch
                    : root.lerp(basePitch, root.cameraMatchPitch, root.cameraMatchWeight)
                eulerRotation.y: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedYaw
                    : root.lerp(baseYaw, root.cameraMatchYaw, root.cameraMatchWeight)
                eulerRotation.z: root.cameraResolvedPoseEnabled
                    ? root.cameraResolvedRoll
                    : root.lerp(root.cameraRoll, root.cameraMatchRoll, root.cameraMatchWeight)
                PerspectiveCamera {
                    id: camera
                    z: cameraRig.animatedDistance
                    clipNear: 8
                    clipFar: 3000
                    fieldOfView: root.cameraResolvedPoseEnabled
                        ? root.cameraResolvedFieldOfView
                        : root.lerp(
                            cameraRig.baseFieldOfView,
                            root.cameraMatchFieldOfView,
                            root.cameraMatchWeight)
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
                    visible: root.effectKind !== "wave"
                    y: root.artworkSurfaceY
                    eulerRotation.x: -90
                    source: "#Rectangle"
                    scale: Qt.vector3d(
                        root.artworkWidth / 100,
                        root.artworkDepth / 100,
                        1
                    )
                    materials: PrincipledMaterial {
                        baseColor: Qt.rgba(
                            root.artworkExposure,
                            root.artworkExposure,
                            root.artworkExposure,
                            1.0
                        )
                        lighting: root.artworkColorMode === "faithful"
                            ? PrincipledMaterial.NoLighting
                            : PrincipledMaterial.FragmentLighting
                        roughness: 0.47
                        baseColorMap: Texture {
                            sourceItem: Image {
                                source: root.artworkSource
                                cache: false
                                asynchronous: false
                            }
                            generateMipmaps: false
                            minFilter: Texture.Linear
                            magFilter: Texture.Linear
                            mipFilter: Texture.None
                        }
                    }
                }

                // The Wave is the artwork: Python updates a dense native mesh from
                // the source-color density. Faithful mode leaves the deformed mesh,
                // depth and silhouette intact without recoloring its source pixels.
                Model {
                    id: organicWaveArtwork
                    visible: root.effectKind === "wave"
                    y: root.artworkSurfaceY + 0.15
                    eulerRotation.x: -90
                    castsShadows: true
                    receivesShadows: true
                    geometry: organicWaveGeometry
                    materials: PrincipledMaterial {
                        baseColor: Qt.rgba(
                            root.artworkExposure,
                            root.artworkExposure,
                            root.artworkExposure,
                            1.0
                        )
                        lighting: root.artworkColorMode === "faithful"
                            ? PrincipledMaterial.NoLighting
                            : PrincipledMaterial.FragmentLighting
                        roughness: 0.47 - 0.25 * root.smootherstep(
                            root.effectProgress / 0.08
                        ) * (1 - root.smootherstep(
                            (root.effectProgress - 0.86) / 0.13
                        ))
                        clearcoatAmount: 0.72 * root.smootherstep(
                            root.effectProgress / 0.08
                        ) * (1 - root.smootherstep(
                            (root.effectProgress - 0.86) / 0.13
                        ))
                        clearcoatRoughnessAmount: 0.08
                        baseColorMap: Texture {
                            sourceItem: Image {
                                source: root.artworkSource
                                cache: false
                                asynchronous: false
                            }
                            generateMipmaps: false
                            minFilter: Texture.Linear
                            magFilter: Texture.Linear
                            mipFilter: Texture.None
                        }
                    }
                }
                // Screenprint stays abstract and premium: one white boundary on
                // the surface, separating deposited ink from the untouched area.
                Node {
                    id: screenprintBoundary
                    readonly property bool active: root.effectKind === "screenprint"
                        || (root.effectKind === "screenprint_laser"
                            && !root.effectToolIsOutline)
                    visible: active
                        && root.effectToolProgress > 0.005
                        && root.effectToolProgress < 0.995
                    x: -root.artworkWidth / 2
                        + root.artworkWidth * root.effectToolProgress

                    Model {
                        id: screenprintWhiteLine
                        y: root.artworkSurfaceY + 0.9
                        source: "#Cube"
                        scale: Qt.vector3d(0.014, 0.005, root.artworkDepth / 100)
                        castsShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#ffffff"
                            emissiveFactor: Qt.vector3d(1.0, 1.0, 1.0)
                            roughness: 0.08
                        }
                    }
                }

                // Halo remains a restrained luminous curtain on the same local plane.
                Node {
                    id: haloBoundary
                    readonly property real travelProgress: root.effectDirection === "right"
                        ? 1.0 - root.effectToolProgress : root.effectToolProgress
                    visible: root.effectKind === "vertical_halo"
                        && root.effectToolProgress > 0.005
                        && root.effectToolProgress < 0.995
                    x: -root.artworkWidth / 2
                        + root.artworkWidth * travelProgress

                    Model {
                        y: root.artworkSurfaceY + 1.2
                        source: "#Cube"
                        scale: Qt.vector3d(0.045, 0.008, root.artworkDepth / 100)
                        castsShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#fff7e9"
                            emissiveFactor: Qt.vector3d(0.82, 0.58, 0.30)
                            opacity: 0.72
                            roughness: 0.12
                        }
                    }
                }

                // The sky ray follows normalized points sampled from the detected
                // outline mask. Being a child of artworkDeck removes all parallax drift.
                Node {
                    id: skyLaserDeck
                    readonly property bool active: root.effectKind === "contour_laser"
                        || (root.effectKind === "screenprint_laser"
                            && root.effectToolIsOutline)
                    visible: active && root.laserCursorOn
                        && root.effectToolProgress > 0.005
                        && root.effectToolProgress < 0.995
                    x: -root.artworkWidth / 2
                        + root.artworkWidth * root.laserCursorU
                    z: (root.laserCursorV - 0.5) * root.artworkDepth

                    Model {
                        id: skyLaserAura
                        y: root.artworkSurfaceY + 311
                        source: "#Cylinder"
                        scale: Qt.vector3d(0.038, 6.4, 0.038)
                        castsShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#ff5d24"
                            emissiveFactor: Qt.vector3d(1.0, 0.13, 0.015)
                            opacity: 0.17
                            roughness: 0.05
                        }
                    }
                    Model {
                        id: skyLaserCore
                        y: root.artworkSurfaceY + 311
                        source: "#Cylinder"
                        scale: Qt.vector3d(0.009, 6.4, 0.009)
                        castsShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#fff8dc"
                            emissiveFactor: Qt.vector3d(1.0, 0.31, 0.04)
                            opacity: 0.96
                            roughness: 0.03
                        }
                    }
                    Model {
                        id: skyLaserImpact
                        y: root.artworkSurfaceY + 1.0
                        source: "#Sphere"
                        scale: Qt.vector3d(0.075, 0.014, 0.075)
                        castsShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#fff1c4"
                            emissiveFactor: Qt.vector3d(1.0, 0.22, 0.02)
                            opacity: 0.82
                            roughness: 0.08
                        }
                    }
                    PointLight {
                        y: root.artworkSurfaceY + 7
                        color: "#ff6a24"
                        brightness: 1.15
                        castsShadow: false
                        quadraticFade: 0.0012
                    }
                }
            }

            // Every grain comes from a real analyzed pixel and settles at its 2D time.
            Repeater3D {
                model: pigmentParticleModel
                delegate: Model {
                    required property real targetU
                    required property real targetV
                    required property color particleColor
                    required property real birthProgress
                    required property real settleProgress
                    required property real driftX
                    required property real driftZ
                    required property real particleSize
                    required property real originU
                    required property real originV
                    required property real overshootU
                    required property real overshootV
                    required property real curlU
                    required property real curlV
                    required property real motionPhase
                    readonly property bool isSweep: root.effectKind === "pigment_sweep"
                    readonly property real motionProgress: isSweep
                        ? root.smootherstep(root.effectProgress) : root.effectProgress
                    readonly property real travel: Math.max(0, Math.min(1,
                        (motionProgress - birthProgress)
                        / Math.max(0.0001, settleProgress - birthProgress)))
                    readonly property real fall: travel * travel
                    readonly property real approach: Math.max(0, Math.min(1, travel / 0.78))
                    readonly property real approachEase: root.smootherstep(approach)
                    readonly property real curlWave: Math.sin(Math.PI * approachEase)
                        * Math.sin(motionPhase + approachEase * Math.PI * 2)
                    readonly property real rebound: Math.max(0, Math.min(1,
                        (travel - 0.78) / 0.22))
                    readonly property real reboundResidual: Math.pow(1 - rebound, 2)
                        * Math.cos(rebound * Math.PI * 1.25)
                    readonly property real reboundCurl: Math.sin(Math.PI * rebound)
                        * (1 - rebound)
                        * Math.sin(motionPhase + rebound * Math.PI) * 0.18
                    readonly property real targetDeckX: (targetU - 0.5) * root.artworkWidth
                    readonly property real targetDeckZ: root.artworkCenterZ
                        + (targetV - 0.5) * root.artworkDepth
                    readonly property real originDeckX: (originU - 0.5) * root.artworkWidth
                    readonly property real originDeckZ: root.artworkCenterZ
                        + (originV - 0.5) * root.artworkDepth
                    readonly property real sweepX: travel < 0.78
                        ? originDeckX
                            + (targetDeckX + overshootU * root.artworkWidth - originDeckX)
                                * approachEase
                            + curlU * root.artworkWidth * curlWave
                        : targetDeckX + overshootU * root.artworkWidth * reboundResidual
                            + curlU * root.artworkWidth * reboundCurl
                    readonly property real sweepZ: travel < 0.78
                        ? originDeckZ
                            + (targetDeckZ + overshootV * root.artworkDepth - originDeckZ)
                                * approachEase
                            + curlV * root.artworkDepth * curlWave
                        : targetDeckZ + overshootV * root.artworkDepth * reboundResidual
                            + curlV * root.artworkDepth * reboundCurl
                    visible: (root.effectKind === "sand" || isSweep)
                        && travel > 0.0 && travel < 1.0
                    x: isSweep ? sweepX
                        : (targetU - 0.5) * root.artworkWidth
                            + driftX * (1 - fall)
                            + Math.sin(targetU * 91 + targetV * 57 + travel * 6.28)
                                * (1 - fall) * 3.2
                    y: isSweep
                        ? root.artworkSurfaceY + 2.2
                            + Math.sin(Math.PI * travel) * (18 + particleSize * 8)
                        : root.artworkSurfaceY + 245 * (1 - fall)
                    z: isSweep ? sweepZ
                        : root.artworkCenterZ + (targetV - 0.5) * root.artworkDepth
                            + driftZ * (1 - fall)
                    source: "#Sphere"
                    scale: isSweep
                        ? Qt.vector3d(
                            particleSize * 3.25 / 100,
                            particleSize * 1.9 / 100,
                            particleSize * 3.25 / 100
                        )
                        : Qt.vector3d(
                            particleSize * 1.55 / 100,
                            particleSize * 3.8 / 100,
                            particleSize * 1.55 / 100
                        )
                    materials: PrincipledMaterial {
                        baseColor: particleColor
                        opacity: isSweep ? 0.91 : 0.82
                        roughness: isSweep ? 0.68 : 0.84
                    }
                }
            }

            // A large autonomous drop falls vertically onto the true analyzed zone.
            Node {
                id: paintDropDeck
                visible: root.effectKind === "paint_drop"
                    && root.effectProgress > 0.005
                    && root.effectProgress < 0.995
                x: -root.artworkWidth / 2 + root.artworkWidth * root.paintTargetU
                z: root.artworkCenterZ + (root.paintTargetV - 0.5)
                    * root.artworkDepth
                eulerRotation.y: -3
                readonly property real fallProgress: Math.min(
                    1.0,
                    root.effectToolProgress / Math.max(root.paintFallRatio, 0.001)
                )
                readonly property real fallEased: root.smootherstep(fallProgress)
                readonly property real impactProgress: Math.max(
                    0.0,
                    Math.min(
                        1.0,
                        (root.effectToolProgress - root.paintFallRatio) / 0.30
                    )
                )
                readonly property real dropScale: Math.max(
                    0.06,
                    Math.min(root.artworkWidth, root.artworkDepth)
                        * root.paintDropSize / 100.0
                )
                readonly property real dropY: root.artworkSurfaceY + 3
                    + 185 * (1.0 - fallEased)

                Model {
                    id: fallingPaintDrop
                    visible: root.effectToolProgress < root.paintFallRatio
                    y: paintDropDeck.dropY
                    source: "#Sphere"
                    castsShadows: false
                    scale: Qt.vector3d(
                        paintDropDeck.dropScale,
                        paintDropDeck.dropScale * (1.28 + 0.34 * (1.0 - paintDropDeck.fallProgress)),
                        paintDropDeck.dropScale
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        emissiveFactor: Qt.vector3d(
                            root.paintActiveColor.r * 0.20,
                            root.paintActiveColor.g * 0.20,
                            root.paintActiveColor.b * 0.20
                        )
                        roughness: 0.10
                        clearcoatAmount: 0.82
                        clearcoatRoughnessAmount: 0.06
                    }
                }
                Model {
                    visible: fallingPaintDrop.visible
                    y: paintDropDeck.dropY + paintDropDeck.dropScale * 82
                    source: "#Cylinder"
                    castsShadows: false
                    scale: Qt.vector3d(
                        paintDropDeck.dropScale * 0.28,
                        paintDropDeck.dropScale * 0.72,
                        paintDropDeck.dropScale * 0.28
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        emissiveFactor: Qt.vector3d(
                            root.paintActiveColor.r * 0.12,
                            root.paintActiveColor.g * 0.12,
                            root.paintActiveColor.b * 0.12
                        )
                        opacity: 0.68
                        roughness: 0.16
                    }
                }
                Model {
                    visible: fallingPaintDrop.visible
                        && paintDropDeck.fallProgress > 0.18
                    x: -paintDropDeck.dropScale * 54
                    y: paintDropDeck.dropY + paintDropDeck.dropScale * 118
                    z: paintDropDeck.dropScale * 24
                    source: "#Sphere"
                    castsShadows: false
                    scale: Qt.vector3d(
                        paintDropDeck.dropScale * 0.26,
                        paintDropDeck.dropScale * 0.38,
                        paintDropDeck.dropScale * 0.26
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        roughness: 0.13
                        clearcoatAmount: 0.72
                    }
                }
                Model {
                    visible: root.effectToolProgress >= root.paintFallRatio
                        && paintDropDeck.impactProgress < 1.0
                    y: root.artworkSurfaceY + 1.1
                    source: "#Cylinder"
                    castsShadows: false
                    scale: Qt.vector3d(
                        0.07 + paintDropDeck.impactProgress * 0.42,
                        0.005,
                        0.07 + paintDropDeck.impactProgress * 0.24
                    )
                    materials: PrincipledMaterial {
                        baseColor: root.paintActiveColor
                        opacity: Math.max(0.0, 0.64 * (1.0 - paintDropDeck.impactProgress))
                        roughness: 0.20
                        clearcoatAmount: 0.36
                    }
                }
                Repeater3D {
                    model: 7
                    delegate: Model {
                        required property int index
                        readonly property real angle: -2.85 + index * 0.52
                        readonly property real distance: 6
                            + paintDropDeck.impactProgress * (13 + (index % 3) * 3)
                        visible: root.effectToolProgress >= root.paintFallRatio
                            && paintDropDeck.impactProgress < 0.92
                        x: Math.cos(angle) * distance
                        y: root.artworkSurfaceY + 2.0
                            + Math.sin(paintDropDeck.impactProgress * Math.PI) * (5 + index % 2 * 3)
                        z: Math.sin(angle) * distance * 0.52
                        source: "#Sphere"
                    castsShadows: false
                        scale: Qt.vector3d(
                            0.025 * (1.0 - paintDropDeck.impactProgress * 0.55),
                            0.018 * (1.0 - paintDropDeck.impactProgress * 0.55),
                            0.025 * (1.0 - paintDropDeck.impactProgress * 0.55)
                        )
                        materials: PrincipledMaterial {
                            baseColor: root.paintActiveColor
                            opacity: 0.82 * (1.0 - paintDropDeck.impactProgress)
                            roughness: 0.16
                        }
                    }
                }
            }


            // Wave geometry and wet pigment shading live on organicWaveArtwork.

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
                || root.effectKind === "paint_drop"
                || root.effectKind === "pigment_sweep"
                || root.effectKind === "wave")
            && root.effectProgress > 0.005
            && root.effectProgress < 0.995
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 18
        radius: 8
        color: "#d0161b25"
        border.color: root.effectKind === "paint_drop"
            ? root.paintActiveColor
            : (root.effectKind === "pigment_sweep"
                ? "#65d7c4"
                : (root.effectKind === "wave"
                    ? "#59b7ef"
                    : (root.effectToolIsOutline ? "#ff6a32" : "#c99a67")))
        border.width: 1
        width: effectActText.implicitWidth + 26
        height: 34

        Text {
            id: effectActText
            anchors.centerIn: parent
            color: root.effectToolIsOutline ? "#ffd1b6" : "#ffe0b9"
            text: root.effectKind === "wave"
                ? "VAGUE 3D · MASSE PIGMENTAIRE · DENSITÉS VARIABLES"
                : root.effectKind === "pigment_sweep"
                ? "PIGMENT SWEEP · CIBLAGE "
                    + (root.effectDirection === "right" ? "DROITE → GAUCHE"
                        : root.effectDirection === "top" ? "HAUT → BAS"
                        : root.effectDirection === "bottom" ? "BAS → HAUT"
                        : "GAUCHE → DROITE")
                : root.effectKind === "paint_drop"
                ? "COUCHE " + (root.effectToolStage + 1) + "/"
                    + root.effectStageCount + " · "
                    + (root.effectToolProgress < root.paintFallRatio
                        ? "GOUTTE EN CHUTE" : "PEINTURE EN EXPANSION")
                : root.effectKind === "screenprint_laser"
                ? (root.effectToolIsOutline
                    ? "ACTE 2 · RAYON DU CIEL · CONTOURS NOIRS"
                    : "ACTE 1 · LIGNE BLANCHE · COULEUR "
                        + (root.effectToolStage + 1) + "/"
                        + Math.max(1, root.effectStageCount - 1))
                : root.effectKind === "screenprint"
                    ? "LIGNE DE SÉRIGRAPHIE · COUCHE " + (root.effectToolStage + 1)
                    : root.effectKind === "contour_laser"
                        ? "RAYON DU CIEL · TRACÉ DES CONTOURS"
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
