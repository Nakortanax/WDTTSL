#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel, text):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_required(text, old, new, label):
    if old not in text:
        raise SystemExit(f"VPNSL 1.0.8 anchor missing: {label}")
    return text.replace(old, new, 1)


# 1.0.8 is UI-only and must keep the exact 1.0.7 / 1.0.5 routing runtime.
tun_rel = "app/src/main/java/com/csqtt/client/TunVpnService.kt"
tun = read(tun_rel)
for marker in [
    "if (routingSourceMode == RoutingSourceMode.APPLICATIONS)",
    "builder.addAllowedApplication(pkg)",
    "RoutePolicyApplier.apply(builder, routeListStore.loadProfiles())",
]:
    if marker not in tun:
        raise SystemExit(f"VPNSL 1.0.8 requires restored 1.0.5 routing marker: {marker}")
if "defaultTarget = RouteTarget.WDTTSL" in tun:
    raise SystemExit("1.0.6 combined runtime leaked into VPNSL 1.0.8")

# Global geometry: remove the rounded/pill visual language throughout the app.
shapes_rel = "app/src/main/java/com/csqtt/client/ui/design/CsqttShapes.kt"
shapes = read(shapes_rel)
shapes = replace_required(shapes, "val Small = RoundedCornerShape(22.dp)", "val Small = RoundedCornerShape(6.dp)", "Small shape")
shapes = replace_required(shapes, "val Control = RoundedCornerShape(percent = 50)", "val Control = RoundedCornerShape(8.dp)", "Control shape")
shapes = replace_required(shapes, "val Card = RoundedCornerShape(34.dp)", "val Card = RoundedCornerShape(10.dp)", "Card shape")
shapes = replace_required(shapes, "val LargeCard = RoundedCornerShape(42.dp)", "val LargeCard = RoundedCornerShape(12.dp)", "LargeCard shape")
shapes = replace_required(shapes, "val Dialog = RoundedCornerShape(40.dp)", "val Dialog = RoundedCornerShape(12.dp)", "Dialog shape")
shapes = replace_required(shapes, "val Pill = RoundedCornerShape(percent = 50)", "val Pill = RoundedCornerShape(8.dp)", "Pill shape")
write(shapes_rel, shapes)

# Bottom navigation inspired by the supplied reference: rectangular icon tile,
# label below, dark flat shell, no large pill spanning icon + label.
main_rel = "app/src/main/java/com/csqtt/client/MainActivity.kt"
main = read(main_rel)
proxy_pattern = re.compile(r"@Composable\nprivate fun ProxyNavigationBar\(.*?\n\}\n\nprivate fun openReleaseUrl", re.S)
proxy = '''@Composable
private fun ProxyNavigationBar(
    navItems: List<NavItem>,
    selectedTab: Int,
    dragTargetIndex: IntState,
    dragProgress: FloatState,
    unreadErrors: Int,
    tunnelRunning: Boolean,
    onTabSelected: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    val colors = MaterialTheme.colorScheme
    val isDark = colors.background.luminance() < 0.22f
    val shellColor = if (isDark) {
        lerp(colors.background, colors.surface, 0.90f)
    } else {
        lerp(colors.surface, colors.surfaceVariant, 0.30f)
    }
    val shellBorder = if (isDark) {
        colors.outlineVariant.copy(alpha = 0.36f)
    } else {
        colors.outline.copy(alpha = 0.14f)
    }
    val selectedVisualIndex = remember(selectedTab, navItems) {
        navItems.indexOfFirst { it.id == selectedTab }.coerceAtLeast(0)
    }
    val dragIndex = dragTargetIndex.intValue
    val visualIndex = if (dragIndex in navItems.indices) {
        selectedVisualIndex.toFloat() +
            (dragIndex - selectedVisualIndex) * dragProgress.floatValue
    } else {
        selectedVisualIndex.toFloat()
    }

    BoxWithConstraints(
        modifier = modifier
            .fillMaxWidth()
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal + WindowInsetsSides.Bottom))
            .padding(horizontal = 10.dp, vertical = 8.dp)
    ) {
        Surface(
            shape = CsqttShapes.Card,
            color = shellColor,
            border = BorderStroke(1.dp, shellBorder),
            tonalElevation = 0.dp,
            shadowElevation = if (isDark) 2.dp else 4.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(72.dp)
                    .padding(horizontal = 4.dp, vertical = 5.dp)
                    .selectableGroup(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                navItems.forEachIndexed { index, item ->
                    val emphasis = (1f - abs(index - visualIndex)).coerceIn(0f, 1f)
                    val active = emphasis > 0.55f
                    val label = stringResource(item.labelRes)
                    val iconBackground = if (active) colors.primary else Color.Transparent
                    val iconColor = if (active) colors.onPrimary else colors.onSurfaceVariant.copy(alpha = 0.78f)
                    val labelColor = if (active) colors.primary else colors.onSurfaceVariant.copy(alpha = 0.78f)

                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight()
                            .clip(CsqttShapes.Small)
                            .selectable(
                                selected = item.id == selectedTab,
                                role = Role.Tab,
                                onClick = { onTabSelected(item.id) },
                            ),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Box(
                            modifier = Modifier
                                .width(50.dp)
                                .height(34.dp)
                                .clip(CsqttShapes.Control)
                                .background(iconBackground),
                            contentAlignment = Alignment.Center,
                        ) {
                            Box(contentAlignment = Alignment.TopEnd) {
                                Icon(
                                    imageVector = if (active) item.selectedIcon else item.unselectedIcon,
                                    contentDescription = null,
                                    modifier = Modifier.size(22.dp),
                                    tint = iconColor,
                                )
                                if (item.id == 4 && unreadErrors > 0) {
                                    Badge(
                                        containerColor = if (tunnelRunning) colors.primary else CSQTTColors.warning,
                                        contentColor = colors.onPrimary,
                                        modifier = Modifier.offset(x = 11.dp, y = (-7).dp),
                                    ) {
                                        Text("$unreadErrors")
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(3.dp))
                        Text(
                            text = label,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium,
                            color = labelColor,
                            maxLines = 1,
                        )
                    }
                }
            }
        }
    }
}

private fun openReleaseUrl'''
main, count = proxy_pattern.subn(proxy, main, count=1)
if count != 1:
    raise SystemExit("VPNSL 1.0.8 anchor missing: ProxyNavigationBar")
write(main_rel, main)

# Connection screen: logo becomes status artwork; a separate wide rectangular
# action button handles connect/disconnect.
connection_rel = "app/src/main/java/com/csqtt/client/ui/ConnectionTab.kt"
connection = read(connection_rel)
connection = replace_required(
    connection,
    '''                modifier = Modifier
                    .size(172.dp)
                    .clip(CsqttShapes.Pill)
                    .clickable(
                        enabled = canToggle,
                        onClick = onToggleTunnel,
                    )
                    .scale(logoScale),''',
    '''                modifier = Modifier
                    .size(132.dp)
                    .scale(logoScale),''',
    "connection logo button",
)
connection = replace_required(
    connection,
    '''    val statusText = when {
        autoPausedForWifi -> "Ожидание. Автопауза при Wi-Fi"
        tunnelStopping -> "Ожидание"
        tunnelRunning -> "Подключено"
        isStarting -> "Подключение"
        cooldownActive -> "Ожидание"
        else -> "Отключено"
    }
''',
    '''    val statusText = when {
        autoPausedForWifi -> "Ожидание. Автопауза при Wi-Fi"
        tunnelStopping -> "Ожидание"
        tunnelRunning -> "Подключено"
        isStarting -> "Подключение"
        cooldownActive -> "Ожидание"
        else -> "Отключено"
    }
    val actionText = when {
        tunnelStopping -> "Отключение…"
        tunnelRunning || autoPausedForWifi -> "Отключить"
        isStarting -> "Отменить подключение"
        else -> "Подключить"
    }
''',
    "connection action text",
)
connection = replace_required(
    connection,
    '''            )

            Text(
                text = statusText,''',
    '''            )

            Surface(
                onClick = onToggleTunnel,
                enabled = canToggle,
                shape = CsqttShapes.Control,
                color = if (activeVisual) {
                    MaterialTheme.colorScheme.surfaceVariant
                } else {
                    MaterialTheme.colorScheme.primary
                },
                contentColor = if (activeVisual) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onPrimary
                },
                border = if (activeVisual) {
                    BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.35f))
                } else {
                    null
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = actionText,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            Text(
                text = statusText,''',
    "connection rectangular action",
)
write(connection_rel, connection)

# Version bump only; routing remains untouched.
gradle_rel = "app/build.gradle.kts"
gradle = read(gradle_rel)
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 1008', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "1.0.8"', gradle, count=1)
write(gradle_rel, gradle)

screen_rel = "app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt"
screen = read(screen_rel).replace("1.0.7 by Sazhaev-IA", "1.0.8 by Sazhaev-IA")
write(screen_rel, screen)

# Verify both UI request and routing invariants.
route_rel = "app/src/main/java/com/csqtt/client/ui/RouteListsSection.kt"
route = read(route_rel)
compiler_rel = "app/src/main/java/com/csqtt/client/routing/RoutePolicyCompiler.kt"
compiler = read(compiler_rel)
checks = {
    "version 1.0.8": 'versionName = "1.0.8"' in read(gradle_rel),
    "version code 1008": 'versionCode = 1008' in read(gradle_rel),
    "header 1.0.8": '1.0.8 by Sazhaev-IA' in read(screen_rel),
    "rectangular small": 'RoundedCornerShape(6.dp)' in read(shapes_rel),
    "rectangular control": 'RoundedCornerShape(8.dp)' in read(shapes_rel),
    "rectangular card": 'RoundedCornerShape(10.dp)' in read(shapes_rel),
    "nav icon tile": '.width(50.dp)' in read(main_rel) and '.height(34.dp)' in read(main_rel),
    "nav rectangular indicator": '.clip(CsqttShapes.Control)' in read(main_rel),
    "connection action": 'text = actionText' in read(connection_rel) and '.height(52.dp)' in read(connection_rel),
    "smaller status logo": '.size(132.dp)' in read(connection_rel),
    "1.0.5 app runtime": 'if (routingSourceMode == RoutingSourceMode.APPLICATIONS)' in tun,
    "1.0.5 global file runtime": 'RoutePolicyApplier.apply(builder, routeListStore.loadProfiles())' in tun,
    "1.0.5 compiler": 'inheritedTarget = RouteTarget.MOBILE' in compiler and 'defaultTarget:' not in compiler,
    "file import": 'store.importProfile(name, text, RouteTarget.WDTTSL)' in route,
    "manual IP/CIDR": 'IP-адрес или подсеть' in route,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.8 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.8: rectangular UI applied; 1.0.5 routing preserved")
