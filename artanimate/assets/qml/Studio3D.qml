import QtQuick
import QtQuick3D

Item {
    id: root
    property url artworkSource: ""
    property real artworkAspect: 1.6
    property real cameraYaw: -18
    property real cameraPitch: -22
    property real cameraDistance: 950
    property real lampBrightness: 2.4
    property real lampMotion: 0.65
    property string effectKind: "sand"
    property string rgbMode: "channels"
    property string effectDirection: "left"
    property real effectProgress: 0.0
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
                y: 48
                eulerRotation.x: root.cameraPitch
                eulerRotation.y: root.cameraYaw
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

            // Pigment falls vertically and settles into coordinates on the horizontal canvas.
            Repeater3D {
                model: 240
                delegate: Model {
                    required property int index
                    readonly property real targetX: -root.artworkWidth / 2
                        + (((index * 73) % 241) / 240) * root.artworkWidth
                    readonly property real targetZ: root.artworkCenterZ - root.artworkDepth / 2
                        + (((index * 47) % 239) / 238) * root.artworkDepth
                    readonly property real birth: (((index * 37) % 241) / 240) * 0.79
                    readonly property real travel: Math.max(0, Math.min(1,
                        (root.effectProgress - birth) / 0.22))
                    readonly property real fall: travel * travel
                    visible: root.effectKind === "sand"
                        && travel > 0.0 && travel < 1.0
                    x: targetX
                        + Math.sin(index * 1.73 + travel * 6.28)
                        * (1 - fall) * (4 + index % 5)
                    y: root.artworkSurfaceY + 245 * (1 - fall)
                    z: targetZ
                        + Math.cos(index * 1.27 + travel * 5.1)
                        * (1 - fall) * (3 + index % 4)
                    source: "#Sphere"
                    scale: Qt.vector3d(
                        0.0055 + (index % 4) * 0.0014,
                        0.017 + (index % 5) * 0.0036,
                        0.0055 + (index % 4) * 0.0014
                    )
                    materials: PrincipledMaterial {
                        baseColor: index % 6 === 0 ? "#d98a45"
                            : index % 6 === 1 ? "#d3aa68"
                            : index % 6 === 2 ? "#a4523e"
                            : index % 6 === 3 ? "#557180"
                            : index % 6 === 4 ? "#6d5876" : "#292420"
                        opacity: 0.78
                        roughness: 0.86
                    }
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
            root.cameraYaw = Math.max(-75, Math.min(75,
                root.cameraYaw + (mouse.x - lastX) * 0.28))
            root.cameraPitch = Math.max(-38, Math.min(2,
                root.cameraPitch + (mouse.y - lastY) * 0.2))
            lastX = mouse.x
            lastY = mouse.y
        }
        onWheel: function(wheel) {
            root.cameraDistance = Math.max(560, Math.min(1180,
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
