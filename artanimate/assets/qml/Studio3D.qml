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

    readonly property real artworkWidth: artworkAspect >= 1.0 ? 300 : 300 * artworkAspect
    readonly property real artworkHeight: artworkAspect >= 1.0 ? 300 / artworkAspect : 300

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

    Rectangle {
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
