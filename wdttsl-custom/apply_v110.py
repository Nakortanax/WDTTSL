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


def replace_required(text, old, new, label, count=1):
    if old not in text:
        raise SystemExit(f"VPNSL 1.0.10 anchor missing: {label}")
    return text.replace(old, new, count)


deploy_rel = "app/src/main/java/com/csqtt/client/ui/DeployOperations.kt"
deploy = read(deploy_rel)

# Normalize the bundled shell installer before every upload. This makes Android
# resilient even if a future packaging step accidentally stores deploy.sh with
# Windows CRLF endings or a UTF-8 BOM.
anchor = '''internal fun deployMode(installInDocker: Boolean): String =
    if (installInDocker) "docker" else "systemd"
'''
replacement = anchor + '''

internal fun normalizeDeployShellScript(value: String): String =
    value
        .removePrefix("\\uFEFF")
        .replace("\\r\\n", "\\n")
        .replace("\\r", "\\n")
'''
deploy = replace_required(deploy, anchor, replacement, "deployMode helper")

old_extract = '''        fun extractAsset(assetName: String): File {
            val target = File(workingDir, assetName)
            context.assets.open(assetName).use { input ->
                FileOutputStream(target).use { output -> input.copyTo(output) }
            }
            if (!target.isFile || target.length() == 0L) {
                throw IOException("Файл $assetName отсутствует или пуст в assets")
            }
            return target
        }
'''
new_extract = '''        fun extractAsset(assetName: String): File {
            val target = File(workingDir, assetName)
            context.assets.open(assetName).use { input ->
                if (assetName.endsWith(".sh")) {
                    val normalized = normalizeDeployShellScript(
                        input.readBytes().toString(Charsets.UTF_8),
                    )
                    if (!normalized.startsWith("#!/")) {
                        throw IOException("Shell-скрипт $assetName не содержит корректный shebang")
                    }
                    if ('\\r' in normalized) {
                        throw IOException("Shell-скрипт $assetName содержит CR после нормализации")
                    }
                    target.writeText(normalized, Charsets.UTF_8)
                } else {
                    FileOutputStream(target).use { output -> input.copyTo(output) }
                }
            }
            if (!target.isFile || target.length() == 0L) {
                throw IOException("Файл $assetName отсутствует или пуст в assets")
            }
            return target
        }
'''
deploy = replace_required(deploy, old_extract, new_extract, "install asset extraction")

old_install_upload = '''        onProgress(0.06f, "Подготовка сервера...")
        sshClient.upload(scriptFile, "/tmp/deploy.sh")

        val deployEnvironment =
'''
new_install_upload = '''        onProgress(0.06f, "Подготовка сервера...")
        sshClient.upload(scriptFile, "/tmp/deploy.sh")
        val scriptCheck = sshClient.execResult(
            "sed -i 's/\\\\r$//' /tmp/deploy.sh && bash -n /tmp/deploy.sh",
            timeout = 10000L,
        )
        if (scriptCheck.exitStatus != 0) {
            throw IOException(
                "Скрипт установки повреждён после загрузки на сервер: " +
                    scriptCheck.output.trim().take(240),
            )
        }
        TunnelManager.addDeploySuccessLog("Скрипт установки проверен на сервере")

        val deployEnvironment =
'''
deploy = replace_required(deploy, old_install_upload, new_install_upload, "remote install script check")

old_uninstall_extract = '''        uninstallScript = File(context.cacheDir, "csqtt-uninstall-\${System.nanoTime()}.sh")
        context.assets.open("deploy.sh").use { input ->
            FileOutputStream(uninstallScript).use { output -> input.copyTo(output) }
        }
        if (!uninstallScript.isFile || uninstallScript.length() == 0L) {
            throw IOException("Не удалось подготовить штатный установщик CSQTT")
        }
        sshClient.upload(uninstallScript, "/tmp/deploy.sh")

        onProgress(0.30f, "Удаление через deploy.sh...")
'''
new_uninstall_extract = '''        uninstallScript = File(context.cacheDir, "csqtt-uninstall-\${System.nanoTime()}.sh")
        context.assets.open("deploy.sh").use { input ->
            val normalized = normalizeDeployShellScript(
                input.readBytes().toString(Charsets.UTF_8),
            )
            if (!normalized.startsWith("#!/") || '\\r' in normalized) {
                throw IOException("Встроенный deploy.sh повреждён")
            }
            uninstallScript.writeText(normalized, Charsets.UTF_8)
        }
        if (!uninstallScript.isFile || uninstallScript.length() == 0L) {
            throw IOException("Не удалось подготовить штатный установщик CSQTT")
        }
        sshClient.upload(uninstallScript, "/tmp/deploy.sh")
        val scriptCheck = sshClient.execResult(
            "sed -i 's/\\\\r$//' /tmp/deploy.sh && bash -n /tmp/deploy.sh",
            timeout = 10000L,
        )
        if (scriptCheck.exitStatus != 0) {
            throw IOException(
                "Скрипт удаления повреждён после загрузки на сервер: " +
                    scriptCheck.output.trim().take(240),
            )
        }

        onProgress(0.30f, "Удаление через deploy.sh...")
'''
deploy = replace_required(deploy, old_uninstall_extract, new_uninstall_extract, "uninstall script normalization")
write(deploy_rel, deploy)

# Add regression tests for the exact CRLF/BOM failure that was observed on the
# home Ubuntu server.
test_rel = "app/src/test/java/com/csqtt/client/ui/DeployResultPolicyTest.kt"
test = read(test_rel)
test_anchor = '''    @Test
    fun serverAssetMatchesTheRemoteVpsArchitecture() {
'''
test_block = '''    @Test
    fun deployShellNormalizationRemovesBomAndWindowsLineEndings() {
        val normalized = normalizeDeployShellScript(
            "\\uFEFF#!/bin/bash\\r\\nset -Eeuo pipefail\\r\\necho ok\\r",
        )
        assertEquals(
            "#!/bin/bash\\nset -Eeuo pipefail\\necho ok\\n",
            normalized,
        )
        assertFalse(normalized.contains('\\r'))
    }

'''
test = replace_required(test, test_anchor, test_block + test_anchor, "normalization unit test")
write(test_rel, test)

preflight_rel = "app/src/test/java/com/csqtt/client/ui/DeployScriptPreflightTest.kt"
preflight = read(preflight_rel)
class_anchor = '''class DeployScriptPreflightTest {
'''
helper_test = '''class DeployScriptPreflightTest {
    @Test
    fun \`bundled deploy script is LF only and Android validates it remotely\`() {
        val candidates = listOf(
            File("app/src/main/assets/deploy.sh"),
            File("src/main/assets/deploy.sh"),
        )
        val scriptFile = candidates.first(File::isFile)
        assertFalse(scriptFile.readBytes().any { it == '\\r'.code.toByte() })

        val client = deployOperations()
        assertTrue(client.contains("normalizeDeployShellScript"))
        assertTrue(client.contains("sed -i 's/\\\\r$//' /tmp/deploy.sh && bash -n /tmp/deploy.sh"))
        assertTrue(client.contains("Скрипт установки проверен на сервере"))
    }

'''
preflight = replace_required(preflight, class_anchor, helper_test, "deploy preflight regression test")
write(preflight_rel, preflight)

# Version bump.
gradle_rel = "app/build.gradle.kts"
gradle = read(gradle_rel)
gradle = re.sub(r'versionCode\\s*=\\s*\\d+', 'versionCode = 1010', gradle, count=1)
gradle = re.sub(r'versionName\\s*=\\s*"[^"]+"', 'versionName = "1.0.10"', gradle, count=1)
write(gradle_rel, gradle)

screen_rel = "app/src/main/java/com/csqtt/client/ui/components/CsqttScreen.kt"
screen = read(screen_rel).replace("1.0.9 by Sazhaev-IA", "1.0.10 by Sazhaev-IA")
write(screen_rel, screen)

# Strong invariants.
deploy_after = read(deploy_rel)
checks = {
    "version 1.0.10": 'versionName = "1.0.10"' in read(gradle_rel),
    "version code 1010": 'versionCode = 1010' in read(gradle_rel),
    "header 1.0.10": '1.0.10 by Sazhaev-IA' in read(screen_rel),
    "normalizer exists": "normalizeDeployShellScript" in deploy_after,
    "install normalizes shell asset": 'if (assetName.endsWith(".sh"))' in deploy_after,
    "remote syntax check": "bash -n /tmp/deploy.sh" in deploy_after,
    "remote CR cleanup": "sed -i 's/\\\\r$//' /tmp/deploy.sh" in deploy_after,
    "install check before binary upload":
        deploy_after.index("Скрипт установки проверен на сервере") <
        deploy_after.index('sshClient.upload(serverFile, "/tmp/.csqtt-upload-server")'),
    "uninstall normalized": "Встроенный deploy.sh повреждён" in deploy_after,
    "unit regression test": "deployShellNormalizationRemovesBomAndWindowsLineEndings" in read(test_rel),
    "asset regression test": "bundled deploy script is LF only and Android validates it remotely" in read(preflight_rel),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("VPNSL 1.0.10 verification failed: " + ", ".join(failed))

print("VPNSL 1.0.10: Android server deployment hardened against CRLF/BOM and corrupted deploy.sh")
