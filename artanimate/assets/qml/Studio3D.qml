import QtQuick
import QtQuick3D

Item {
    id: root
    property url artworkSource: ""
    property real artworkAspect: 1.6
    property real cameraYaw: -10
    property real cameraPitch: -9
    property real cameraDistance: 900
    property real lampBrightness: 2.2
    property string effectKind: "sand"
    property string rgbMode: "channels"
    property string effectDirection: "left"
    property real effectProgress: 0.0
    property real outputAspect: 16 / 9
    property bool showHud: true

    readonly property real artworkWidth: artworkAspect >= 1.0 ? 280 : 280 * artworkAspect
    readonly property real artworkHeight: artworkAspect >= 1.0 ? 280 / artworkAspect : 280
    readonly property real tableTopY: -35
    readonly property real artworkBottomY: tableTopY + 4
    readonly property real artworkCenterY: artworkBottomY + artworkHeight / 2

    function rgbWeight(channel) {
        if (rgbMode === "together")
            return effectProgress
        const start = channel * 0.25
        return Math.max(0, Math.min(1, (effectProgress - start) / 0.5))
    }

    Rectangle {
        anchors.fill: parent
        color: "#07090c"
    }

    View3D {
        id: view
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#07090c"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.VeryHigh
            temporalAAEnabled: true
            aoEnabled: true
            aoStrength: 68
            aoDistance: 12
            aoSoftness: 52
        }

        Node {
            id: scene

            Node {
                id: cameraRig
                y: 45
                eulerRotation.x: root.cameraPitch
                eulerRotation.y: root.cameraYaw
                PerspectiveCamera {
                    id: camera
                    z: root.cameraDistance
                    clipNear: 20
                    clipFar: 2800
                    fieldOfView: 40
                }
            }

            // The room stays deliberately empty: architecture, table, artwork, light.
            DirectionalLight {
                eulerRotation.x: -48
                eulerRotation.y: -32
                color: "#a7b6ca"
                ambientColor: "#11151b"
                brightness: 0.22
            }

            Model {
                id: floor
                y: -170
                source: "#Cube"
                scale: Qt.vector3d(13, 0.1, 10)
                materials: PrincipledMaterial {
                    baseColor: "#14161b"
                    roughness: 0.9
                    metalness: 0.04
                }
            }
            Model {
                id: backWall
                y: 245
                z: -430
                source: "#Cube"
                scale: Qt.vector3d(13, 8.4, 0.1)
                materials: PrincipledMaterial {
                    baseColor: "#191a1e"
                    roughness: 0.98
                }
            }
            Model {
                id: leftWall
                x: -650
                y: 245
                source: "#Cube"
                scale: Qt.vector3d(0.1, 8.4, 10)
                materials: PrincipledMaterial {
                    baseColor: "#0e1013"
                    roughness: 0.98
                }
            }
            Model {
                id: rightWall
                x: 650
                y: 245
                source: "#Cube"
                scale: Qt.vector3d(0.1, 8.4, 10)
                materials: PrincipledMaterial {
                    baseColor: "#0e1013"
                    roughness: 0.98
                }
            }

            // A single oval poker table anchors the room.
            Model {
                id: pokerTablePedestal
                y: -109
                source: "#Cylinder"
                scale: Qt.vector3d(0.72, 1.22, 0.72)
                materials: PrincipledMaterial {
                    baseColor: "#17120f"
                    metalness: 0.22
                    roughness: 0.5
                }
            }
            Model {
                y: -158
                source: "#Cylinder"
                scale: Qt.vector3d(1.9, 0.15, 1.32)
                materials: PrincipledMaterial {
                    baseColor: "#0d0c0c"
                    metalness: 0.26
                    roughness: 0.48
                }
            }
            Model {
                id: pokerTableBody
                y: -58
                source: "#Cylinder"
                scale: Qt.vector3d(4.9, 0.28, 2.72)
                materials: PrincipledMaterial {
                    baseColor: "#17100d"
                    roughness: 0.52
                }
            }
            Model {
                id: pokerTableRail
                y: -43
                source: "#Cylinder"
                scale: Qt.vector3d(4.9, 0.14, 2.72)
                materials: PrincipledMaterial {
                    baseColor: "#362117"
                    metalness: 0.08
                    roughness: 0.46
                }
            }
            Model {
                id: pokerTableFelt
                y: -34
                source: "#Cylinder"
                scale: Qt.vector3d(4.46, 0.045, 2.34)
                materials: PrincipledMaterial {
                    baseColor: "#164b3d"
                    roughness: 0.96
                    metalness: 0.0
                }
            }

            // The framed artwork is placed directly on the felt.
            Model {
                y: root.artworkCenterY
                z: -28
                source: "#Cube"
                scale: Qt.vector3d(
                    (root.artworkWidth + 24) / 100,
                    (root.artworkHeight + 24) / 100,
                    0.10
                )
                materials: PrincipledMaterial {
                    baseColor: "#090a0c"
                    metalness: 0.38
                    roughness: 0.26
                }
            }
            Model {
                y: root.artworkCenterY
                z: -20
                source: "#Rectangle"
                scale: Qt.vector3d(
                    root.artworkWidth / 100,
                    root.artworkHeight / 100,
                    1
                )
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    roughness: 0.5
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
            Repeater3D {
                model: 2
                delegate: Model {
                    required property int index
                    x: index === 0 ? -root.artworkWidth * 0.28 : root.artworkWidth * 0.28
                    y: root.tableTopY + 6
                    z: -8
                    source: "#Cube"
                    scale: Qt.vector3d(0.18, 0.12, 0.34)
                    materials: PrincipledMaterial {
                        baseColor: "#0b0b0d"
                        metalness: 0.3
                        roughness: 0.32
                    }
                }
            }

            // Fine pigment streams converge on their actual positions in the artwork.
            Repeater3D {
                model: 196
                delegate: Model {
                    required property int index
                    readonly property real targetX: -root.artworkWidth / 2
                        + (((index * 73) % 197) / 196) * root.artworkWidth
                    readonly property real targetY: root.artworkBottomY
                        + (((index * 47) % 193) / 192) * root.artworkHeight
                    readonly property real birth: (((index * 37) % 197) / 196) * 0.78
                    readonly property real travel: Math.max(0, Math.min(1,
                        (root.effectProgress - birth) / 0.20))
                    readonly property real fall: travel * travel
                    visible: root.effectKind === "sand"
                        && travel > 0.0 && travel < 1.0
                    x: targetX
                        + Math.sin(index * 1.73 + travel * 6.28)
                        * (1 - fall) * (5 + index % 5)
                    y: root.artworkBottomY + root.artworkHeight + 62
                        + (targetY - root.artworkBottomY - root.artworkHeight - 62) * fall
                    z: -8 + (index % 9) * 1.35
                    source: "#Sphere"
                    scale: Qt.vector3d(
                        0.006 + (index % 4) * 0.0017,
                        0.018 + (index % 5) * 0.004,
                        0.006 + (index % 4) * 0.0017
                    )
                    materials: PrincipledMaterial {
                        baseColor: index % 6 === 0 ? "#d98a45"
                            : index % 6 === 1 ? "#d3aa68"
                            : index % 6 === 2 ? "#a4523e"
                            : index % 6 === 3 ? "#557180"
                            : index % 6 === 4 ? "#6d5876" : "#292420"
                        opacity: 0.82
                        roughness: 0.84
                    }
                }
            }

            Model {
                readonly property bool horizontalFront: root.effectDirection === "left"
                    || root.effectDirection === "right"
                visible: root.effectKind === "wave"
                    && root.effectProgress > 0.01
                    && root.effectProgress < 0.99
                x: horizontalFront
                    ? (root.effectDirection === "right" ? 1 : -1)
                        * root.artworkWidth * (0.5 - root.effectProgress)
                    : 0
                y: horizontalFront
                    ? root.artworkCenterY
                    : root.artworkBottomY + root.artworkHeight
                        * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress)
                z: -5
                eulerRotation.z: root.effectDirection === "diagonal" ? -24 : 0
                source: root.effectDirection === "radial" ? "#Cylinder" : "#Cube"
                eulerRotation.x: root.effectDirection === "radial" ? 90 : 0
                scale: root.effectDirection === "radial"
                    ? Qt.vector3d(
                        0.22 + root.effectProgress * 1.5,
                        0.015,
                        0.22 + root.effectProgress * 1.5
                    )
                    : horizontalFront
                        ? Qt.vector3d(0.026, root.artworkHeight / 100, 0.045)
                        : Qt.vector3d(root.artworkWidth / 100, 0.026, 0.045)
                materials: PrincipledMaterial {
                    baseColor: "#68b9e8"
                    emissiveFactor: Qt.vector3d(0.12, 0.34, 0.56)
                    opacity: root.effectDirection === "radial" ? 0.22 : 0.68
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
                        * root.artworkWidth * (0.5 - root.effectProgress)
                    : Math.sin(root.effectProgress * 18) * 7
                y: horizontalFront
                    ? root.artworkCenterY + Math.sin(root.effectProgress * 18) * 6
                    : root.artworkBottomY + root.artworkHeight
                        * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress) - 7
                z: -7
                eulerRotation.z: root.effectDirection === "diagonal" ? -24 : 0
                source: "#Cube"
                scale: horizontalFront
                    ? Qt.vector3d(0.012, root.artworkHeight / 105, 0.065)
                    : Qt.vector3d(root.artworkWidth / 105, 0.012, 0.065)
                materials: PrincipledMaterial {
                    baseColor: "#b5e1f6"
                    emissiveFactor: Qt.vector3d(0.22, 0.42, 0.62)
                    opacity: 0.42
                    roughness: 0.18
                }
            }

            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: -190
                y: root.artworkCenterY + 35
                z: 110
                color: "#ff3348"
                brightness: root.rgbWeight(0) * 1.15
                quadraticFade: 0.000012
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 0
                y: root.artworkCenterY + 80
                z: 95
                color: "#36df77"
                brightness: root.rgbWeight(1) * 1.05
                quadraticFade: 0.000012
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 190
                y: root.artworkCenterY + 25
                z: 110
                color: "#4385ff"
                brightness: root.rgbWeight(2) * 1.2
                quadraticFade: 0.000012
            }

            // Floating poker suspension: cable, sculpted shade and warm pool of light.
            Model {
                id: overheadLampCable
                x: 0
                y: 410
                z: 45
                source: "#Cylinder"
                scale: Qt.vector3d(0.025, 1.3, 0.025)
                materials: PrincipledMaterial {
                    baseColor: "#08090a"
                    metalness: 0.62
                    roughness: 0.24
                }
            }
            Model {
                id: overheadLamp
                x: 0
                y: 316
                z: 45
                source: "#Cone"
                scale: Qt.vector3d(1.34, 0.66, 1.34)
                materials: PrincipledMaterial {
                    baseColor: "#18110d"
                    metalness: 0.58
                    roughness: 0.31
                }
            }
            Model {
                x: 0
                y: 284
                z: 45
                source: "#Cylinder"
                scale: Qt.vector3d(1.34, 0.035, 1.34)
                materials: PrincipledMaterial {
                    baseColor: "#bf8251"
                    emissiveFactor: Qt.vector3d(0.16, 0.09, 0.045)
                    roughness: 0.5
                }
            }
            Model {
                x: 0
                y: 275
                z: 45
                source: "#Sphere"
                scale: Qt.vector3d(0.16, 0.16, 0.16)
                materials: PrincipledMaterial {
                    baseColor: "#ffd6a1"
                    emissiveFactor: Qt.vector3d(0.72, 0.48, 0.24)
                    roughness: 0.25
                }
            }
            SpotLight {
                x: 0
                y: 270
                z: 45
                eulerRotation.x: -90
                color: "#ffd1a0"
                brightness: root.lampBrightness * 3.2
                coneAngle: 70
                innerConeAngle: 44
                castsShadow: true
            }
            PointLight {
                x: 0
                y: 262
                z: 45
                color: "#ffc58c"
                ambientColor: "#20150d"
                brightness: root.lampBrightness * 0.62
                constantFade: 1.0
                linearFade: 0.004
                quadraticFade: 0.000013
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
            root.cameraPitch = Math.max(-30, Math.min(2,
                root.cameraPitch + (mouse.y - lastY) * 0.2))
            lastX = mouse.x
            lastY = mouse.y
        }
        onWheel: function(wheel) {
            root.cameraDistance = Math.max(560, Math.min(1150,
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
