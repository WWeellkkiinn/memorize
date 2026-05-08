import QtQuick
import QtQuick.Window
import QtQuick.Controls 2.15

Window {
    id: rootWin
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: true

    property var word: ({})        // active (FSRS) word — expanded popup
    property var passiveWord: ({}) // passive bar word — collapsed bar
    property var _displayPassiveWord: ({})
    property real sf: (typeof scaleFactor !== "undefined") ? scaleFactor : 1.0

    // Reveal phase: 0=collapsed, 1=self-test (CN hidden), 2=revealed
    property int _revealPhase: 0
    readonly property int _revealSeconds: 3
    property int _countdown: _revealSeconds

    function resetReveal() {
        _revealPhase = 1
        _countdown = _revealSeconds
        revealTimer.restart()
        countdownTimer.restart()
    }
    function doReveal() {
        _revealPhase = 2
        revealTimer.stop()
        countdownTimer.stop()
    }

    // Style helpers
    readonly property int _fs:   Math.round(11 * sf)
    readonly property int _fsLg: Math.round(13 * sf)
    readonly property int _br:   Math.round(6 * sf)

    // Safe accessors for active word
    function wordText()       { return word.word       || "" }
    function phoneticText()   { return word.phonetic   || "" }
    function posText()        { return word.pos        || "" }
    function definitionText() { return word.definition || "" }
    function wordId()         { return word.word_id    || 0 }

    // Cached parsed examples (active word only)
    property var _parsedExamples: []
    onWordChanged: {
        try { _parsedExamples = JSON.parse(word.examples || "[]") }
        catch(e) { _parsedExamples = [] }
    }
    function examples() { return _parsedExamples }

    onPassiveWordChanged: {
        if (container.open) {
            _displayPassiveWord = passiveWord
        } else {
            passiveFader.restart()
        }
    }

    Connections {
        target: bridge
        function onWordChanged(w) {
            // Reset phase BEFORE updating word so CN text is already opacity:0
            // when the new word's bindings evaluate — prevents one-frame flash
            if (container.open) rootWin.resetReveal()
            rootWin.word = w
        }
        function onPassiveWordChanged(w) { rootWin.passiveWord = w }
        function onExpandTriggered() {
            container.open = true
            rootWin.resetReveal()
        }
        function onCollapseTriggered()   { container.open = false }
    }

    // ── Container ─────────────────────────────────────────────────────────────
    Item {
        id: container
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }

        readonly property int barH: Math.round(20 * rootWin.sf)
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
            if (open) {
                rootWin.resetReveal()
                maskShrinkTimer.stop()
                _maskH = height
                bridge.setVisibleHeight(height)
            } else {
                rootWin._revealPhase = 0
                rootWin._countdown = rootWin._revealSeconds
                revealTimer.stop()
                countdownTimer.stop()
                maskShrinkTimer.restart()
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

        Timer { id: leaveTimer;      interval: 300;  onTriggered: container.open = false }
        Timer { id: maskShrinkTimer; interval: 300;  onTriggered: { container._maskH = container.barH; bridge.setVisibleHeight(container.barH) } }
        Timer { id: revealTimer;    interval: rootWin._revealSeconds * 1000; onTriggered: rootWin.doReveal() }
        Timer { id: countdownTimer; interval: 1000; repeat: true; onTriggered: { if (rootWin._countdown > 1) rootWin._countdown-- } }

        // ── Main rect ─────────────────────────────────────────────────────────
        Rectangle {
            id: mainRect
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }

            readonly property int cardPad: Math.round(20 * rootWin.sf)
            height: container.open
                    ? (container.barH + cardPad + cardCol.implicitHeight)
                    : container.barH
            Behavior on height { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

            color: "transparent"
            clip: true

            Rectangle {
                anchors.fill: parent
                color: "#15171D"
                readonly property real r: Math.round(10 * rootWin.sf)
                topLeftRadius: r; topRightRadius: r
                bottomLeftRadius: r; bottomRightRadius: r
            }

            // ── Detail card (expanded — active word, two phases) ──────────────
            Column {
                id: cardCol
                anchors {
                    top: parent.top; topMargin: Math.round(10 * rootWin.sf)
                    left: parent.left; leftMargin: Math.round(12 * rootWin.sf)
                    right: parent.right; rightMargin: Math.round(12 * rootWin.sf)
                }
                spacing: Math.round(6 * rootWin.sf)
                enabled: container.open
                opacity: container.open ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                // Word header: pos badge + word + phonetic
                Row {
                    spacing: Math.round(6 * rootWin.sf)

                    Rectangle {
                        id: posBadge
                        visible: rootWin.posText() !== ""
                        width: posLabel.implicitWidth + Math.round(8 * rootWin.sf)
                        height: posLabel.implicitHeight + Math.round(2 * rootWin.sf)
                        radius: Math.round(3 * rootWin.sf)
                        color: "transparent"
                        border.color: "#475569"; border.width: 1
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
                        text: rootWin.wordText()
                        color: "#F1F5F9"
                        font { pixelSize: rootWin._fsLg; bold: true; family: "Microsoft YaHei UI" }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Text {
                        text: rootWin.phoneticText() ? "/" + rootWin.phoneticText() + "/" : ""
                        color: "#94A3B8"
                        font { pixelSize: rootWin._fs; family: "Consolas" }
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                // Phase 1: countdown hint; Phase 2: CN definition (same element, no blank line)
                Text {
                    width: parent.width
                    text: rootWin._revealPhase >= 2
                          ? (rootWin.definitionText() || "暂无释义")
                          : ("单击查看答案，" + rootWin._countdown + " 秒后自动揭示")
                    color: rootWin._revealPhase >= 2 ? "#F1F5F9" : "#475569"
                    font { pixelSize: rootWin._fsLg; bold: true; family: "Microsoft YaHei UI" }
                    wrapMode: Text.WordWrap
                    Behavior on color { ColorAnimation { duration: 200 } }
                }

                // Divider + examples (EN always visible; CN phase 2 only)
                Rectangle {
                    width: parent.width; height: 1; color: "#2D3748"
                    visible: rootWin.examples().length > 0
                }

                Repeater {
                    model: Math.min(rootWin.examples().length, 2)
                    delegate: Column {
                        width: parent.width
                        spacing: Math.round(2 * rootWin.sf)

                        Text {
                            width: parent.width
                            text: rootWin.examples()[index] ? rootWin.examples()[index].en : ""
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fsLg; family: "Microsoft YaHei UI" }
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            id: cnExText
                            width: parent.width
                            text: rootWin.examples()[index] ? rootWin.examples()[index].zh : ""
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fsLg; family: "Microsoft YaHei UI" }
                            wrapMode: Text.WordWrap
                            state: rootWin._revealPhase >= 2 ? "shown" : "hidden"
                            states: [
                                State { name: "hidden"; PropertyChanges { target: cnExText; opacity: 0.0 } },
                                State { name: "shown";  PropertyChanges { target: cnExText; opacity: 1.0 } }
                            ]
                            transitions: Transition {
                                from: "hidden"; to: "shown"
                                NumberAnimation { property: "opacity"; duration: 200 }
                            }
                        }
                    }
                }

            }

            // Click-to-reveal overlay — covers entire popup above barArea (phase 1 only)
            MouseArea {
                anchors { top: parent.top; left: parent.left; right: parent.right; bottom: barArea.top }
                z: -1
                enabled: rootWin._revealPhase === 1
                onClicked: rootWin.doReveal()
            }

            // ── Bar area — passive word (collapsed) / rating buttons (phase 2) ─
            Item {
                id: barArea
                anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
                height: container.barH

                // Drag + click-to-reveal handler
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
                    onClicked: { if (!dragging && rootWin._revealPhase === 1) rootWin.doReveal() }
                }

                // Passive word — fades out when popup opens, fades in/out on word change
                Item {
                    anchors {
                        left: parent.left; leftMargin: Math.round(10 * rootWin.sf)
                        right: parent.right; rightMargin: Math.round(10 * rootWin.sf)
                        verticalCenter: parent.verticalCenter
                    }
                    height: parent.height
                    opacity: container.open ? 0.0 : 1.0
                    Behavior on opacity { NumberAnimation { duration: 200 } }

                    Row {
                        id: passiveRow
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Math.round(8 * rootWin.sf)

                        Text {
                            id: passiveWordText
                            text: rootWin._displayPassiveWord.word || "—"
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fsLg; bold: true; family: "Microsoft YaHei UI" }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: rootWin._displayPassiveWord.definition || ""
                            color: "#F1F5F9"
                            font { pixelSize: rootWin._fs; family: "Microsoft YaHei UI" }
                            elide: Text.ElideRight
                            width: barArea.width - Math.round(20 * rootWin.sf)
                                   - passiveWordText.implicitWidth - Math.round(8 * rootWin.sf)
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    SequentialAnimation {
                        id: passiveFader
                        NumberAnimation { target: passiveRow; property: "opacity"; to: 0.0; duration: 200 }
                        ScriptAction { script: rootWin._displayPassiveWord = rootWin.passiveWord }
                        NumberAnimation { target: passiveRow; property: "opacity"; to: 1.0; duration: 200 }
                    }
                }

                // Rating buttons — appear in phase 2, replacing passive word
                Row {
                    anchors.centerIn: parent
                    spacing: Math.round(6 * rootWin.sf)
                    opacity: rootWin._revealPhase >= 2 ? 1.0 : 0.0
                    enabled: rootWin._revealPhase >= 2 && rootWin.wordId() !== 0
                    Behavior on opacity { NumberAnimation { duration: 150 } }

                    Repeater {
                        model: [
                            { label: "忘了", rating: 1, base: "#7F1D1D", hover: "#991B1B" },
                            { label: "模糊", rating: 2, base: "#92400E", hover: "#B45309" },
                            { label: "记得", rating: 3, base: "#1E3A5F", hover: "#1D4ED8" },
                            { label: "轻松", rating: 4, base: "#065F46", hover: "#047857" }
                        ]
                        delegate: Rectangle {
                            readonly property var btn: modelData
                            width: Math.round(62 * rootWin.sf)
                            height: Math.round(16 * rootWin.sf)
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
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
