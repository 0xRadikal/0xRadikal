# Profile artwork

This directory contains the Raydikalx artwork used by the English and Persian profile READMEs.

## Rebuild

From the repository root, run:

```sh
python3 tools/build_profile_assets.py
```

The generator uses only the Python standard library. It writes six deterministic SVGs and embeds the original PNG directly, so rendering the SVGs needs no external image, font or statistics service.

## Brand source

`brand-original.png` is the unchanged embedded PNG from the author's public [Free-Telegram-Proxy hero](https://github.com/0xRadikal/Free-Telegram-Proxy/blob/main/assets/readme/hero.svg), read on 2026-11-01.

- Source SVG Git blob: `91763600521c6e4f3ef8df7bf5c19e05ba1935c8`.
- PNG SHA-256: `0ae50d5ae3d7fcb25eb8ca958888f6e984e49f64658d8920b8117bfb5c6a6a5c`.
- The original monogram is embedded, never reconstructed from a font or a new path.
- Palette: electric blue `#247EFD`, deeper blue shading and cool white `#EFF2F9`.
- A deeper blue behind small lettering improves contrast. The logo's own colors and pixels are unchanged.

Desktop and mobile compositions have separate view boxes. The READMEs select them with GitHub-supported `picture` markup. Only a decorative line in the hero animates; `prefers-reduced-motion` disables it. Titles, descriptions, alt text and the native Markdown carry the content without animation.

## Content maintenance

Update `README.md` and `README_FA.md` together. Keep descriptions tied to repository documentation and manifests, and keep source visibility separate from product availability.

The portfolio review covered the account's public repository inventory, available public READMEs, relevant dependency manifests and the two featured publishing workflows. The flagship verification descriptions were also checked against their pipeline source. This is a presentation update, not a new audit of the linked applications.

Useful source references:

| Content | Source |
| :--- | :--- |
| V2Ray collection and verification | [README](https://github.com/0xRadikal/Free-v2ray-Configs) · [pipeline](https://github.com/0xRadikal/Free-v2ray-Configs/blob/main/scripts/pipeline.py) |
| Telegram proxy verification and lists | [README](https://github.com/0xRadikal/Free-Telegram-Proxy) · [pipeline](https://github.com/0xRadikal/Free-Telegram-Proxy/blob/main/tgproxy/pipeline.py) |
| OpenVPN confidence levels | [ovpn-checker](https://github.com/0xRadikal/ovpn-checker) |
| Packet diagnostics | [PPPoE / VLAN / GPON](https://github.com/0xRadikal/pppoe-vlan-gpon-diagnostics) |
| On-chain research | [pons launchpad forensics](https://github.com/0xRadikal/pons-launchpad-forensics) |
| Presentation stack | [PoWeb-Point package.json](https://github.com/0xRadikal/PoWeb-Point/blob/main/package.json) |
| Industrial website stack | [Foam-Sanat package.json](https://github.com/0xRadikal/Foam-Sanat/blob/main/package.json) |
| Academic writing workflow | [Academic Paper Writer](https://github.com/0xRadikal/Academic-Paper-Writer-Skill) |
| Responsive images | [GitHub formatting documentation](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#the-picture-element) |

The profile deliberately avoids numerical claims about audience size, uptime, income, test counts or response times that this review could not independently substantiate. It does not link to private repositories or include implementation details from them. High-level private project summaries are included in the portfolio; their code remains private.
