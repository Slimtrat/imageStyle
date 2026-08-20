import QtQuick
import QtQuick3D

Item {
    id: root
    property url artworkSource: ""
    property real artworkAspect: 1.6
    property real cameraYaw: -18
    property real cameraPitch: -11
    property real cameraDistance: 780
    property real lampBrightness: 1.8
    property string effectKind: "sand"
    property string rgbMode: "channels"
    property string effectDirection: "left"
    property real effectProgress: 0.0
    property real outputAspect: 16 / 9
    property bool showHud: true

    readonly property real artworkWidth: artworkAspect >= 1.0 ? 300 : 300 * artworkAspect
    readonly property real artworkHeight: artworkAspect >= 1.0 ? 300 / artworkAspect : 300
    readonly property real artworkCenterY: -35 + artworkHeight / 2

    function rgbWeight(channel) {
        if (rgbMode === "together")
            return effectProgress
        const start = channel * 0.25
        return Math.max(0, Math.min(1, (effectProgress - start) / 0.5))
    }

    Rectangle {
        anchors.fill: parent
        color: "#11151f"
    }

    View3D {
        id: view
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#11151f"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.VeryHigh
            temporalAAEnabled: true
            aoEnabled: true
            aoStrength: 45
            aoDistance: 5
            aoSoftness: 35
        }

        Node {
            id: scene

            Node {
                id: cameraRig
                y: -5
                eulerRotation.x: root.cameraPitch
                eulerRotation.y: root.cameraYaw
                PerspectiveCamera {
                    id: camera
                    z: root.cameraDistance
                    clipNear: 20
                    clipFar: 2500
                    fieldOfView: 42
                }
            }

            DirectionalLight {
                eulerRotation.x: -36
                eulerRotation.y: -28
                color: "#c9d5ff"
                ambientColor: "#252b3a"
                brightness: 0.45
            }

            PointLight {
                x: -275
                y: 105
                z: 85
                color: "#ffd39b"
                ambientColor: "#2b2118"
                brightness: root.lampBrightness
                castsShadow: true
                constantFade: 0.9
                linearFade: 0.003
                quadraticFade: 0.000002
            }

            // Floor and walls form a real room so light and shadows have context.
            Model {
                y: -165
                source: "#Cube"
                scale: Qt.vector3d(10, 0.1, 7)
                materials: PrincipledMaterial {
                    baseColor: "#25272d"
                    roughness: 0.92
                }
            }
            Model {
                y: 235
                z: -345
                source: "#Cube"
                scale: Qt.vector3d(10, 8, 0.1)
                materials: PrincipledMaterial {
                    baseColor: "#34343b"
                    roughness: 0.96
                }
            }
            Model {
                x: -500
                y: 235
                source: "#Cube"
                scale: Qt.vector3d(0.1, 8, 7)
                materials: PrincipledMaterial {
                    baseColor: "#2c2d34"
                    roughness: 0.96
                }
            }

            // Solid wood table.
            Model {
                y: -62
                source: "#Cube"
                scale: Qt.vector3d(4.5, 0.18, 2.35)
                materials: PrincipledMaterial {
                    baseColor: "#513426"
                    roughness: 0.66
                }
            }
            Repeater3D {
                model: 4
                delegate: Model {
                    required property int index
                    x: index % 2 === 0 ? -190 : 190
                    y: -115
                    z: index < 2 ? -82 : 82
                    source: "#Cube"
                    scale: Qt.vector3d(0.22, 1.05, 0.22)
                    materials: PrincipledMaterial {
                        baseColor: "#3f291f"
                        roughness: 0.7
                    }
                }
            }

            // Framed artwork standing on the table.
            Model {
                y: -35 + root.artworkHeight / 2
                z: -28
                source: "#Cube"
                scale: Qt.vector3d(
                    (root.artworkWidth + 28) / 100,
                    (root.artworkHeight + 28) / 100,
                    0.11
                )
                materials: PrincipledMaterial {
                    baseColor: "#111217"
                    metalness: 0.18
                    roughness: 0.34
                }
            }
            Model {
                y: -35 + root.artworkHeight / 2
                z: -20
                source: "#Rectangle"
                scale: Qt.vector3d(
                    root.artworkWidth / 100,
                    root.artworkHeight / 100,
                    1
                )
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    roughness: 0.46
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

            // Effect-specific volumes make the selected 2D construction inhabit the room.
            Repeater3D {
                model: 42
                delegate: Model {
                    required property int index
                    readonly property real fallPhase: (root.effectProgress * 2.4 + index * 0.137) % 1.0
                    visible: root.effectKind === "sand"
                        && root.effectProgress > 0.01
                        && root.effectProgress < 0.99
                    x: -root.artworkWidth / 2
                        + (((index * 73) % 101) / 100) * root.artworkWidth
                    y: -35 + root.artworkHeight * (1.12 - fallPhase * 1.25)
                    z: -4 + (index % 6) * 2.2
                    source: "#Sphere"
                    scale: Qt.vector3d(
                        0.018 + (index % 4) * 0.004,
                        0.028 + (index % 3) * 0.006,
                        0.018 + (index % 4) * 0.004
                    )
                    materials: PrincipledMaterial {
                        baseColor: index % 6 === 0 ? "#e15d4f"
                            : index % 6 === 1 ? "#e8ad3d"
                            : index % 6 === 2 ? "#55a36b"
                            : index % 6 === 3 ? "#3d76c2"
                            : index % 6 === 4 ? "#8759b5" : "#30333a"
                        roughness: 0.72
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
                    : -35 + root.artworkHeight
                        * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress)
                z: -5
                eulerRotation.z: root.effectDirection === "diagonal" ? -24 : 0
                source: root.effectDirection === "radial" ? "#Cylinder" : "#Cube"
                eulerRotation.x: root.effectDirection === "radial" ? 90 : 0
                scale: root.effectDirection === "radial"
                    ? Qt.vector3d(
                        0.22 + root.effectProgress * 1.6,
                        0.018,
                        0.22 + root.effectProgress * 1.6
                    )
                    : horizontalFront
                        ? Qt.vector3d(0.035, root.artworkHeight / 100, 0.055)
                        : Qt.vector3d(root.artworkWidth / 100, 0.035, 0.055)
                materials: PrincipledMaterial {
                    baseColor: "#4aa6e8"
                    emissiveFactor: Qt.vector3d(0.18, 0.42, 0.72)
                    opacity: root.effectDirection === "radial" ? 0.28 : 0.82
                    roughness: 0.22
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
                    : Math.sin(root.effectProgress * 18) * 9
                y: horizontalFront
                    ? root.artworkCenterY + Math.sin(root.effectProgress * 18) * 7
                    : -35 + root.artworkHeight
                        * (root.effectDirection === "top"
                            ? 1 - root.effectProgress : root.effectProgress) - 8
                z: -8
                eulerRotation.z: root.effectDirection === "diagonal" ? -24 : 0
                source: "#Cube"
                scale: horizontalFront
                    ? Qt.vector3d(0.018, root.artworkHeight / 105, 0.08)
                    : Qt.vector3d(root.artworkWidth / 105, 0.018, 0.08)
                materials: PrincipledMaterial {
                    baseColor: "#a4ddff"
                    emissiveFactor: Qt.vector3d(0.34, 0.54, 0.78)
                    opacity: 0.55
                    roughness: 0.18
                }
            }

            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: -190
                y: root.artworkCenterY + 40
                z: 115
                color: "#ff2f45"
                brightness: root.rgbWeight(0) * 1.4
                quadraticFade: 0.00001
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 0
                y: root.artworkCenterY + 100
                z: 95
                color: "#38e477"
                brightness: root.rgbWeight(1) * 1.25
                quadraticFade: 0.00001
            }
            PointLight {
                visible: root.effectKind === "rgb_fade"
                x: 190
                y: root.artworkCenterY + 30
                z: 115
                color: "#4182ff"
                brightness: root.rgbWeight(2) * 1.45
                quadraticFade: 0.00001
            }

            // Burlesque table lamp: weighted base, stem and broad shade.
            Model {
                x: -275
                y: -45
                z: 35
                source: "#Cylinder"
                scale: Qt.vector3d(0.42, 0.12, 0.42)
                materials: PrincipledMaterial {
                    baseColor: "#2c3038"
                    metalness: 0.75
                    roughness: 0.28
                }
            }
            Model {
                x: -275
                y: 17
                z: 35
                source: "#Cylinder"
                scale: Qt.vector3d(0.09, 1.15, 0.09)
                materials: PrincipledMaterial {
                    baseColor: "#343943"
                    metalness: 0.82
                    roughness: 0.24
                }
            }
            Model {
                x: -275
                y: 102
                z: 35
                source: "#Cone"
                scale: Qt.vector3d(0.78, 0.7, 0.78)
                materials: PrincipledMaterial {
                    baseColor: "#c79a66"
                    roughness: 0.62
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
            root.cameraYaw = Math.max(-85, Math.min(85,
                root.cameraYaw + (mouse.x - lastX) * 0.28))
            root.cameraPitch = Math.max(-32, Math.min(2,
                root.cameraPitch + (mouse.y - lastY) * 0.2))
            lastX = mouse.x
            lastY = mouse.y
        }
        onWheel: function(wheel) {
            root.cameraDistance = Math.max(560, Math.min(1100,
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
