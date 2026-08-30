# Durcissement production du Studio V3

Le Studio reste un client Python entièrement local. Ses frontières asynchrones
(aperçu, analyse, waveform, médias et export) renvoient des `UserProblem` structurés :
un code stable, un message utilisateur, une action de récupération et des détails
techniques pour les logs. Les fichiers manquants, médias illisibles, erreurs GPU,
codecs indisponibles, droits Windows, disque plein et destinations invalides ne sont
donc plus affichés comme des exceptions brutes.

## Cycle de vie

Chaque contrôleur possède son propre `ThreadPoolExecutor` : deux workers au maximum
pour le proxy, un pour l’analyse, un pour les waveforms et un pour l’export. Une
fermeture annule les travaux, réveille la passerelle 3D, attend les futures, ferme le
pool et libère les caches/surfaces. Un contrôleur fermé ne peut pas accepter de
nouvelle tâche. Les fichiers vidéo, audio, projet et analyse utilisent des écritures
temporaires suivies d’un remplacement atomique ; l’annulation nettoie les temporaires.

## Budgets locaux

Les limites par défaut sont explicites et testées :

| Ressource | Budget par contrôleur |
|---|---:|
| frames proxy compositées | 128 Mio |
| œuvres RGB décodées | 96 Mio |
| images réelles décodées | 128 Mio |
| références + frames d’effets 2D | 128 Mio |
| frames vidéo décodées | 128 Mio |
| surfaces Qt Quick 3D | 3 résolutions en LRU |

Le registre expose `cache_bytes` et `cache_budget_bytes`. Un média actif plus grand
que son budget reste utilisable, mais n’est pas conservé dans le cache. Les sources
vidéo évincées ferment immédiatement leur processus de décodage. Les tests de charge
couvrent 300 seeks vidéo non séquentiels, 600 plans sur une timeline, les limites en
octets et l’extinction effective des threads.

## Build Windows autonome

La recette `packaging/windows/build.ps1` résout d’abord le Python demandé puis réduit
son `PATH` aux répertoires Python et Windows. Cela empêche PyInstaller de capturer des
DLL CRT provenant d’un JDK, de Codex ou d’un autre outil de développement.

Le one-file embarque Python, PySide6/Qt Quick 3D et le FFmpeg fourni par
`imageio-ffmpeg`. Après chaque build, l’EXE lance lui-même un diagnostic caché qui :

- construit puis ferme la vraie fenêtre principale et l’espace Studio ;
- vérifie que FFmpeg est extrait depuis le bundle, jamais depuis le système ;
- contrôle `libx264`, `libvpx-vp9`, `aac` et `libopus` ;
- encode puis redécode une sonde H.264.

Le build échoue si une de ces étapes échoue. Deux rapports restent dans `dist` :
`ArtAnimate-self-test.json` et `ArtAnimate-build.json`.

Mesure de référence du 30 août 2026 sur Windows 11, Python 3.13.6, PyInstaller
6.22.2 : **219,6 Mio**, **115,9 s**, SHA-256
`74432AAE302DE15537F0D8F3172E84FE6A9A61AC74BEDDA60E6C1A4362E881FD`.
La taille et le temps sont informatifs : seul l’échec du build ou du diagnostic bloque
la livraison.
