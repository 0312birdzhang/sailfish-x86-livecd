import QtQuick 2.0
import QtQuick.Window 2.2

Window {
    id: window
    width: 1024
    height: 768
    visible: true
    visibility: Window.FullScreen
    color: "#142638"
    property double started: Date.now()
    property var frameTimes: []
    onFrameSwapped: {
        var now = Date.now()
        if (now - started >= 2000) frameTimes.push(now)
    }
    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.height
        interactive: false
        clip: true
        NumberAnimation on contentY {
            from: 0
            to: 4000
            duration: 10000
            loops: Animation.Infinite
        }
        Column {
            id: column
            width: parent.width
            Repeater {
                model: 80
                Rectangle {
                    width: column.width
                    height: 100
                    color: index % 2 ? "#275b72" : "#183e56"
                    opacity: 0.9
                    Text {
                        anchors.centerIn: parent
                        text: "Sailfish Qt Quick scrolling — row " + index
                        color: "white"
                        font.pixelSize: 24
                    }
                }
            }
        }
    }
    Timer {
        interval: 12000
        running: true
        onTriggered: {
            var intervals = []
            for (var i = 1; i < frameTimes.length; ++i)
                intervals.push(frameTimes[i] - frameTimes[i - 1])
            intervals.sort(function(a, b) { return a - b })
            var elapsed = frameTimes.length > 1 ? frameTimes[frameTimes.length - 1] - frameTimes[0] : 0
            console.log("SFOS_SCROLL_STATS " + JSON.stringify({
                frames: frameTimes.length,
                fps: elapsed ? (frameTimes.length - 1) * 1000 / elapsed : 0,
                median_ms: intervals.length ? intervals[Math.floor(intervals.length / 2)] : null,
                p95_ms: intervals.length ? intervals[Math.floor((intervals.length - 1) * 0.95)] : null
            }))
            Qt.quit()
        }
    }
}
