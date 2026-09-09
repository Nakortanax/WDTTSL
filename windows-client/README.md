# VPNSL 1.0.8 for Windows

Windows x64 port of the VPNSL Android 1.0.8 client.

## What is preserved

- Existing VPNSL/CSQTT Rust transport and wire protocol.
- Peer/password/VK hash settings, worker count, obfuscation, TURN transport, captcha/auth parameters.
- IPv4/CIDR routing profiles.
- Import of `.bat`, `.txt`, and `.list` route files.
- Per-profile target: `VPNSL` or `MOBILE` (normal Windows network).
- Enable/disable route profiles.
- BAT export compatible with the Android 1.0.8 route format.
- Site-to-IPv4 BAT generator.
- Connection logs and traffic statistics.

## Intentional Windows difference

Android application selection is not implemented and is not present in the Windows UI. Windows routing is based only on IP/CIDR route profiles and imported route files.

## Architecture

`VPNSL.Windows.exe` creates a Wintun adapter and starts the existing `client.exe` in its native UDP packet mode. Raw IPv4 packets are bridged:

`Windows route -> Wintun -> local UDP -> client.exe -> VPNSL server`

The server returns `TUNCONF:<ip>:<dns>` through the same event protocol used by Android. The Windows client applies that IP/DNS to Wintun, then installs the enabled route policy.

The default Windows route remains on the physical network. Only enabled `VPNSL` prefixes enter Wintun. A more-specific `MOBILE` prefix can override a broader VPNSL prefix.

## Package

Keep these files in the same directory:

- `VPNSL.Windows.exe`
- `client.exe`
- `wintun.dll`

Run `VPNSL.Windows.exe`. It requests Administrator rights because Wintun, interface IP/DNS, and route-table changes require elevation.

## Current limitation

The Windows UI currently uses manual VK hashes. Android Auto JS/WebView account bootstrapping is not exposed yet in the Windows UI. The VPN transport itself is the same Rust client as Android 1.0.8.
