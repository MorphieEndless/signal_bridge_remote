package com.yingti.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.outlined.Bluetooth
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.yingti.app.BridgeState
import kotlin.math.roundToInt

private enum class SuctionPanel { TOY, FREE }
private data class ToyPreset(val label: String, val mode: Int, val level: Int, val detail: String)

private val toyPresets = listOf(
    ToyPreset("1", 5, 1, "持续·弱"),
    ToyPreset("2", 5, 2, "持续·中"),
    ToyPreset("3", 5, 3, "持续·强"),
    // 4/5/6 → byte4 06/07/08，v0.10.0 真机初步确认可用，顺序校准待定。
    ToyPreset("4", 6, 3, "节奏 06"),
    ToyPreset("5", 7, 3, "节奏 07"),
    ToyPreset("6", 8, 3, "节奏 08"),
)

// 真机定论去重后的 6 个有效模式（02=03 抖动、08=01 脉冲均同一模式，已合并）。
private val suctionModes = listOf(
    5 to "持续",
    1 to "脉冲",
    2 to "抖动",
    4 to "另类脉冲",
    6 to "节奏 A",
    7 to "节奏 B",
)

// 震动档位语义（v0.10.x 实测整理；7-9 档尚未逐档校准，不显示描述）。
private val vibDescriptions = mapOf(
    0 to "停止",
    1 to "持续",
    2 to "波浪",
    3 to "尖锐波浪",
    4 to "长振循环",
    5 to "断续",
    6 to "中震×6 + 强震×2",
    10 to "满功率",
)

@Composable
fun DashboardScreen(
    state: BridgeState,
    server: String,
    darkTheme: Boolean,
    devMode: Boolean,
    onToggleTheme: () -> Unit,
    onScan: () -> Unit,
    onVibrate: (Double) -> Unit,
    onStop: () -> Unit,
    onSettings: () -> Unit,
    onLogout: () -> Unit,
    onRawFrame: (String) -> Unit = {},
    onSuction: (Double, Int) -> Unit = { _, _ -> },
) {
    var slider by remember(state.intensity) { mutableFloatStateOf(state.intensity / 10f) }
    var suctionPanel by remember { mutableStateOf(SuctionPanel.TOY) }
    var suctionMode by remember(state.suctionMode) { mutableIntStateOf(state.suctionMode.coerceIn(1, 8)) }
    var suctionLevel by remember(state.suctionIntensity) {
        mutableFloatStateOf(state.suctionIntensity.coerceIn(1, 5).toFloat())
    }
    val selectedToy = toyPresets.indexOfFirst {
        state.suctionIntensity > 0 && it.mode == state.suctionMode && it.level == state.suctionIntensity
    }

    Scaffold(
        topBar = {
            Row(
                Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 12.dp, bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("樱媞 Bridge", style = MaterialTheme.typography.headlineSmall)
                    Text(
                        server.removePrefix("https://"),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                IconButton(onClick = onToggleTheme) {
                    Icon(
                        if (darkTheme) Icons.Outlined.LightMode else Icons.Outlined.DarkMode,
                        if (darkTheme) "切换亮色" else "切换深色",
                    )
                }
                IconButton(onClick = onSettings) { Icon(Icons.Outlined.Settings, "连接设置") }
                IconButton(onClick = onLogout) { Icon(Icons.Outlined.Logout, "清除凭证并退出") }
                // v0.11.1: 红色急停已从顶栏移入设备卡右上角（见下），顶栏只留 3 个图标。
            }
        }
    ) { padding ->
        Column(
            Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                StatusCard(Modifier.weight(1f), Icons.Outlined.Bluetooth, "蓝牙", state.bleStatus)
                StatusCard(Modifier.weight(1f), Icons.Outlined.Cloud, "Relay", state.relayStatus)
            }

            Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surface, tonalElevation = 2.dp) {
                Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    // 设备卡头部：设备名 + 状态在左，红色急停按钮固定在右上角（v0.11.1 起）。
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(state.deviceName ?: "SX589B", style = MaterialTheme.typography.titleLarge)
                            Text(state.lastMessage, color = MaterialTheme.colorScheme.secondary)
                        }
                        Box(
                            Modifier
                                .size(44.dp)
                                .background(Color(0xFFB3261E), CircleShape)
                                .clickable(onClick = onStop),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Filled.Stop, "STOP ALL", tint = Color.White, modifier = Modifier.size(24.dp))
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Text("震动", style = MaterialTheme.typography.titleMedium)
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text("${(slider * 10).roundToInt()}", style = MaterialTheme.typography.displayMedium)
                        Text(" / 10 档", modifier = Modifier.padding(bottom = 8.dp), color = MaterialTheme.colorScheme.secondary)
                    }
                    Slider(
                        value = slider,
                        onValueChange = { slider = it },
                        onValueChangeFinished = { onVibrate(slider.toDouble()) },
                        steps = 9,
                    )
                    val level = (slider * 10).roundToInt()
                    vibDescriptions[level]?.let { desc ->
                        Text(
                            "档位 $level · $desc",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        TextButton(onClick = onScan) { Text("重新扫描") }
                    }
                }
            }

            SuctionCard(
                panel = suctionPanel,
                selectedToy = selectedToy,
                mode = suctionMode,
                level = suctionLevel,
                onPanelChange = { suctionPanel = it },
                onToyPreset = { preset ->
                    suctionMode = preset.mode
                    suctionLevel = preset.level.toFloat()
                    onSuction(preset.level / 5.0, preset.mode)
                },
                onModeChange = { suctionMode = it },
                onLevelChange = { suctionLevel = it },
                onApplyFree = { onSuction(suctionLevel / 5.0, suctionMode) },
                onStopSuction = { onSuction(0.0, suctionMode) },
            )

            state.error?.let {
                Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(14.dp)) {
                    Text(it, Modifier.fillMaxWidth().padding(14.dp), color = MaterialTheme.colorScheme.onErrorContainer)
                }
            }

            if (devMode) {
                ProtocolDebugCard(lastMessage = state.lastMessage, onSendRaw = onRawFrame)
            }

            Text(
                "断网、Relay 断开或服务退出时会自动发送停止帧。设备卡右上角红色停止按钮 = 双通道 STOP ALL。",
                modifier = Modifier.fillMaxWidth().padding(bottom = 18.dp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
}

@Composable
private fun SuctionCard(
    panel: SuctionPanel,
    selectedToy: Int,
    mode: Int,
    level: Float,
    onPanelChange: (SuctionPanel) -> Unit,
    onToyPreset: (ToyPreset) -> Unit,
    onModeChange: (Int) -> Unit,
    onLevelChange: (Float) -> Unit,
    onApplyFree: () -> Unit,
    onStopSuction: () -> Unit,
) {
    Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surface, tonalElevation = 2.dp) {
        Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("吮吸", style = MaterialTheme.typography.titleLarge)
                    Text("模式与 1-5 档强度独立控制", color = MaterialTheme.colorScheme.secondary)
                }
                TextButton(onClick = onStopSuction) { Text("停止") }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = panel == SuctionPanel.TOY,
                    onClick = { onPanelChange(SuctionPanel.TOY) },
                    label = { Text("玩具档") },
                    modifier = Modifier.weight(1f),
                )
                FilterChip(
                    selected = panel == SuctionPanel.FREE,
                    onClick = { onPanelChange(SuctionPanel.FREE) },
                    label = { Text("自由模式") },
                    modifier = Modifier.weight(1f),
                )
            }

            if (panel == SuctionPanel.TOY) {
                toyPresets.chunked(3).forEachIndexed { rowIndex, row ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        row.forEachIndexed { columnIndex, preset ->
                            val index = rowIndex * 3 + columnIndex
                            ElevatedButton(
                                onClick = { onToyPreset(preset) },
                                modifier = Modifier.weight(1f).height(72.dp),
                                // v0.11.1: 收窄内边距 + 副标题允许两行换行，修复「持续·弱」被截成「持续…」。
                                contentPadding = PaddingValues(horizontal = 4.dp, vertical = 4.dp),
                                colors = if (selectedToy == index) {
                                    ButtonDefaults.elevatedButtonColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
                                } else ButtonDefaults.elevatedButtonColors(),
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(
                                        preset.label,
                                        style = MaterialTheme.typography.titleLarge,
                                        maxLines = 1,
                                    )
                                    Text(
                                        preset.detail,
                                        style = MaterialTheme.typography.labelSmall,
                                        textAlign = TextAlign.Center,
                                        maxLines = 2,
                                        softWrap = true,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        }
                    }
                }
            } else {
                Text("模式 byte4 · ${mode.toString().padStart(2, '0')}", style = MaterialTheme.typography.titleMedium)
                suctionModes.chunked(2).forEach { row ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        row.forEach { (value, label) ->
                            FilterChip(
                                selected = mode == value,
                                onClick = { onModeChange(value) },
                                label = { Text(label) },
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                }
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(level.roundToInt().toString(), style = MaterialTheme.typography.displaySmall)
                    Text(" / 5 档强度", modifier = Modifier.padding(bottom = 8.dp), color = MaterialTheme.colorScheme.secondary)
                }
                Slider(
                    value = level,
                    onValueChange = onLevelChange,
                    valueRange = 1f..5f,
                    steps = 3,
                )
                Button(onClick = onApplyFree, modifier = Modifier.fillMaxWidth()) {
                    Text("应用模式 ${mode.toString().padStart(2, '0')} · ${level.roundToInt()}/5")
                }
            }
        }
    }
}

/** 状态卡：绿=已连接，蓝=进行中（扫描/连接/发现服务），灰=断开/未开启。 */
@Composable
private fun StatusCard(modifier: Modifier, icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, status: String) {
    val dotColor = when {
        status.contains("已连接") -> Color(0xFF2E7D32)
        status.contains("扫描") || status.contains("连接") || status.contains("发现服务") -> Color(0xFF2E6FB5)
        else -> Color(0xFF9E9E9E)
    }
    Surface(modifier, shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.surface, tonalElevation = 1.dp) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, null)
                Spacer(Modifier.weight(1f))
                Box(Modifier.size(9.dp).background(dotColor, CircleShape))
            }
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(status, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary)
        }
    }
}

private val quickFrames = listOf(
    "已验证·7字节" to listOf(
        "震动5档 55 03 00 00 05 01 00",
        "震动满 55 03 00 00 0A 01 00",
        "增强帧 55 03 00 00 05 05 00",
        "停止 55 03 00 00 00 00 00",
    ),
    "吮吸·模式与强度" to listOf(
        "持续5 55 09 00 00 05 05 00",
        "脉冲5 55 09 00 00 01 05 00",
        "节奏3 55 09 00 00 06 03 00",
        "停止 55 09 00 00 00 00 00",
    ),
    "校准·02/03 抖动" to listOf(
        "抖动02 55 09 00 00 02 03 00",
        "抖动03 55 09 00 00 03 03 00",
    ),
)

@Composable
private fun ProtocolDebugCard(lastMessage: String, onSendRaw: (String) -> Unit) {
    var hex by remember { mutableStateOf("55 03 00 00 01 01 00") }
    Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surfaceVariant, tonalElevation = 1.dp) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("协议调试", style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = hex,
                    onValueChange = { hex = it },
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodySmall,
                    label = { Text("HEX 帧") },
                )
                Button(onClick = { if (hex.isNotBlank()) onSendRaw(hex) }) { Text("发送") }
            }
            quickFrames.forEach { (group, frames) ->
                Text(group, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
                frames.forEach { frame ->
                    val label = frame.substringBefore(' ')
                    val bytes = frame.substringAfter(' ')
                    AssistChip(
                        onClick = { onSendRaw(bytes) },
                        label = { Text("$label · $bytes", style = MaterialTheme.typography.bodySmall) },
                    )
                }
            }
            Text("最近: $lastMessage", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary)
        }
    }
}
