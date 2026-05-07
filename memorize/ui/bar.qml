import QtQuick
import QtQuick.Window
import QtQuick.Controls 2.15

Window {
    id: rootWin
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: true

    property var word: ({})
    property real sf: (typeof scaleFactor !== "undefined") ? scaleFactor : 1.0

    // Style helpers
    readonly property int _fs:   Math.round(11 * sf)
    readonly property int _fsLg: Math.round(13 * sf)
    readonly property int _br:   Math.round(6 * sf)

    // Helpers to safely read nested word data
    function wordText()       { return word.word       || "" }
    function phoneticText()   { return word.phonetic   || "" }
    function posText()        { return word.pos        || "" }
    function definitionText() { return word.definition || "" }
    function wordId()         { return word.word_id    || 0 }

    // Cached parsed examples — recomputed only when word changes, not on every binding eval
    property var _parsedExamples: []
    onWordChanged: {
        try { _parsedExamples = JSON.parse(word.examples || "[]") }
        catch(e) { _parsedExamples = [] }
    }
    function examples() { return _parsedExamples }

    Connections {
        target: bridge
        function onWordChanged(w)         { rootWin.word = w }
        function onExpandTriggered()      { container.open = true }
        function onCollapseTriggered()    { container.open = false }
    }

    // ── Container ─────────────────────────────────────────────────────────────
    Item {
        id: container
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }

        readonly property int barH: Math.round(24 * rootWin.sf)
        property bool open: false
        property real _maskH: 0

        height: mainRect.height

        onHeightChanged: {
            if (height >= _maskH) {
                _maskH = height
                bridge.setVisibleHeight(height)
            }
        }
        onOpenChanged: {
            if (!open) {
                maskShrinkTimer.restart()
            } else {
                maskShrinkTimer.stop()
                _maskH = height
                bridge.setVisibleHeight(height)
            }
        }

        TapHandler { acceptedButtons: Qt.RightButton; onDoubleTapped: bridge.quit() }

        HoverHandler {
            onHoveredChanged: {
                if (hovered) {
                    leaveTimer.stop()
                    maskShrinkTimer.stop()
                    bridge.onHoverEnter()
                    container.open = true
                } else {
                    bridge.onHoverLeave()
                    leaveTimer.restart()
                }
            }
        }

        Timer { id: leaveTimer;      interval: 300; onTriggered: container.open = false }
        Timer { id: maskShrinkTimer; interval: 300; onTriggered: { container._maskH = container.height; bridge.setVisibleHeight(container.height) } }

        // ── Main rect ─────────────────────────────────────────────────────────
        Rectangle {
            id: mainRect
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }

            readonly property int cardPad: Math.round(16 * rootWin.sf)
            height: container.open
                    ? (container.barH + cardPad + cardCol.implicitHeight)
                    : container.barH
            Behavior on height { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

            color: "transparent"
            clip: true

            // Background with full rounded corners
            Rectangle {
                anchors.fill: parent
                color: "#15171D"
                readonly property real r: Math.round(10 * rootWin.sf)
                topLeftRadius: r; topRightRadius: r
                bottomLeftRadius: r; bottomRightRadius: r
            }

            // ── Detail card (expanded only) ───────────────────────────────────
            Column {
                id: cardCol
                anchors {
                    top: parent.top; topMargin: Math.round(10 * rootWin.sf)
                    left: parent.left; leftMargin: Math.round(14 * rootWin.sf)
                    right: parent.right; rightMargin: Math.round(14 * rootWin.sf)
                }
                spacing: Math.round(6 * rootWin.sf)
                enabled: container.open
                opacity: container.open ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                // Pos + Definition inline
                Row {
                    id: posDefRow
                    width: parent.width
                    spacing: Math.round(6 * rootWin.sf)
                    readonly property bool hasPos: rootWin.posText() !== ""

                    Rectangle {
                        id: posBadge
                        visible: posDefRow.hasPos
                        width: posLabel.implicitWidth + Math.round(8 * rootWin.sf)
                        height: posLabel.implicitHeight + Math.round(2 * rootWin.sf)
                        radius: Math.round(3 * rootWin.sf)
                        color: "transparent"
                        border.color: "#475569"
                        border.width: 1
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            id: posLabel
                            anchors.centerIn: parent
                            text: rootWin.posText()
                            color: "#7DD3FC"
                            font { pixelSize: rootWin._fs; family: "Consolas" }
                        }
                    }

                    Text {
                        width: posDefRow.width - (posDefRow.hasPos ? posBadge.width + posDefRow.spacing : 0)
                        text: rootWin.definitionText() || "暂无释义"
                        color: "#F1F5F9"
                        font { pixelSize: rootWin._fsLg; bold: true; family: "Microsoft YaHei UI" }
                        wrapMode: Text.WordWrap
                    }
                }

                // Divider
                Rectangle {
                    width: parent.width; height: 1
                    color: "#2D3748"
                    visible: rootWin.examples().length > 0
                }

                // Examples (up to 2)
                Repeater {
                    model: {
                        var ex = rootWin.examples()
                        return Math.min(ex.length, 2)
                    }
                    delegate: Column {
                        width: parent.width
                        spacing: Math.round(2 * rootWin.sf)

                        Text {
                            width: parent.width
                            text: rootWin.examples()[index] ? rootWin.examples()[index].en : ""
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fs; family: "Microsoft YaHei UI" }
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            width: parent.width
                            text: rootWin.examples()[index] ? rootWin.examples()[index].zh : ""
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fs; family: "Microsoft YaHei UI" }
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                Rectangle {
                    width: parent.width; height: 1; color: "#2D3748"
                    visible: rootWin.wordId() !== 0
                }

                // FSRS rating buttons
                Item {
                    width: parent.width
                    height: Math.round(26 * rootWin.sf)

                    Row {
                        anchors.centerIn: parent
                        spacing: Math.round(6 * rootWin.sf)
                        enabled: rootWin.wordId() !== 0

                        Repeater {
                            model: [
                                { label: "忘了",  rating: 1, base: "#7F1D1D", hover: "#991B1B" },
                                { label: "模糊",  rating: 2, base: "#92400E", hover: "#B45309" },
                                { label: "记得",  rating: 3, base: "#1E3A5F", hover: "#1D4ED8" },
                                { label: "轻松",  rating: 4, base: "#065F46", hover: "#047857" }
                            ]
                            delegate: Rectangle {
                                readonly property var btn: modelData
                                width: Math.round(58 * rootWin.sf)
                                height: Math.round(26 * rootWin.sf)
                                radius: rootWin._br
                                color: _ratingMA.containsMouse ? btn.hover : btn.base
                                Behavior on color { ColorAnimation { duration: 80 } }

                                Text {
                                    anchors.centerIn: parent
                                    text: btn.label
                                    color: "#F1F5F9"
                                    font { pixelSize: rootWin._fs; bold: true; family: "Microsoft YaHei UI" }
                                }
                                MouseArea {
                                    id: _ratingMA
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        bridge.rate(rootWin.wordId(), btn.rating)
                                        container.open = false
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ── Bar area (always visible) ─────────────────────────────────────
            Item {
                id: barArea
                anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                height: container.barH

                // Drag handler
                MouseArea {
                    anchors.fill: parent; z: 0
                    acceptedButtons: Qt.LeftButton; preventStealing: true
                    cursorShape: dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    property real _startMouseX: 0
                    property real _startWinX: 0
                    property bool dragging: false
                    readonly property int dragThreshold: Math.round(6 * rootWin.sf)
                    onPressed: function(m) {
                        _startMouseX = mapToGlobal(m.x, m.y).x
                        _startWinX = rootWin.x
                        dragging = false
                    }
                    onPositionChanged: function(m) {
                        var dx = mapToGlobal(m.x, m.y).x - _startMouseX
                        if (!dragging && Math.abs(dx) >= dragThreshold) dragging = true
                        if (dragging) bridge.moveBarX(_startWinX + dx)
                    }
                    onReleased: function(m) {
                        if (dragging) bridge.saveBarX(rootWin.x)
                        dragging = false
                    }
                    onCanceled: dragging = false
                }

                // Word text (center)
                Text {
                    anchors { left: parent.left; leftMargin: Math.round(10 * rootWin.sf); verticalCenter: parent.verticalCenter }
                    text: rootWin.wordText() || "—"
                    color: "#F1F5F9"
                    font { pixelSize: rootWin._fsLg; bold: true; family: "Microsoft YaHei UI" }
                }

                // Phonetic (right of word)
                Text {
                    anchors { left: parent.left; leftMargin: Math.round(80 * rootWin.sf); verticalCenter: parent.verticalCenter }
                    text: rootWin.phoneticText() ? ("/" + rootWin.phoneticText() + "/") : ""
                    color: "#F1F5F9"
                    font { pixelSize: rootWin._fs; family: "Consolas" }
                    elide: Text.ElideRight
                    width: Math.round(180 * rootWin.sf)
                }

            }
        }
    }
}
