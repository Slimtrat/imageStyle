# Qualification produit ArtAnimate V3

La qualification finale n’est pas un POC : elle exécute depuis le binaire Windows
monofichier le parcours de production d’un Reel local complet et conserve ses preuves.

## Scénario figé

- projet vertical 1080 × 1920, 30 FPS, 12 secondes ;
- œuvre locale générée puis importée comme point de départ ;
- deux plans caméra 2D et un plan 3D, avec quatre keyframes 2D ;
- un calque d’effet 2D au milieu du second plan ;
- une photo réelle recadrée et reliée au plan 3D par un match manuel ;
- une musique WAV locale, avec point d’entrée, durée, gain et fondus ;
- enregistrement, fermeture logique, rechargement et nouveau rendu des frames de contrôle ;
- export MP4 en mode audio de référence, puis avec audio intégré ;
- décodage des deux exports et ajout des deux résultats à l’historique Studio.

La commande ne sollicite ni réseau, ni interpréteur Python externe, ni FFmpeg système.
Elle refuse de valider la release si elle n’est pas exécutée depuis l’EXE ou si FFmpeg
n’est pas situé dans le bundle PyInstaller.

## Exécution de release

Après la construction de `dist/ArtAnimate.exe` :

```powershell
.\packaging\windows\qualify-v3.ps1
```

Le dossier `dist/v3-qualification` contient le projet rouvert, les médias locaux, les
deux MP4, l’historique, le rapport `ArtAnimate-v3-qualification.json` et la planche
`qualification-controles-visuels.jpg`.

## Critères automatiques bloquants

- le modèle contient toutes les briques du scénario et reste strictement identique
  après sauvegarde/rechargement ;
- les frames de contrôle avant et après rechargement sont identiques au pixel ;
- l’aperçu et les deux exports restent sous les seuils de dérive dus à H.264 ;
- les deux modes d’export conservent la même vidéo ;
- le mode référence ne contient pas d’audio et le mode intégré contient un signal ;
- les deux exports sont décodables depuis l’historique et leurs vignettes existent ;
- au moins cinq états visuels distincts sont observés sur les sept contrôles.

## Revue visuelle humaine

La planche présente, pour chaque frame, quatre colonnes : aperçu, projet réouvert,
export de référence et export avec audio. Avant publication, vérifier :

- absence de frame noire, de média manquant ou de diagnostic rouge ;
- continuité du cadrage entre les deux plans 2D ;
- effet 2D visible sans masquer l’œuvre ;
- volume, lumière et mouvement perceptibles dans le plan 3D ;
- transition lisible vers la photo réelle et alignement visuel plausible ;
- absence de différence perceptible entre aperçu, réouverture et exports ;
- lecture complète des deux MP4, et musique présente uniquement dans l’export intégré.

Les mesures et observations de la qualification de release sont consignées ci-dessous
après exécution du binaire final.

## Résultat de release

Qualification effectuée le 30 août 2026 sur Windows 11 depuis l’EXE ArtAnimate
3.0.0 final : **réussie**.

- suite source complète : 416 tests réussis ;
- build one-file isolé : 107,8 s, 230 290 024 octets ;
- SHA-256 de `ArtAnimate.exe` :
  `0005A10384F222CB4DE7B7650D065BAA67E2899C2CF166114DC0525C2C7747F5` ;
- qualification packagée : 184,1 s, sans Python externe ni réseau ;
- FFmpeg 7.1 issu du bundle, H.264/VP9/AAC/Opus et round-trip H.264 validés ;
- projet et digest strictement identiques après réouverture ;
- six frames rouvertes identiques au pixel, variation maximale d’un niveau RGB sur
  un seul pixel de la frame de transition 3D ;
- écart moyen aperçu → H.264 compris entre 1,4791 et 1,6887, 99e percentile ≤ 9 ;
- deux exports de 1080 × 1920, 30 FPS et exactement 360 frames ;
- export de référence sans flux audio ; export intégré avec 576 000 échantillons,
  flux décodable et pic mesuré à 0,292872 ;
- deux sorties et leurs vignettes relues depuis l’historique Studio.

Revue de `qualification-controles-visuels.jpg` : les quatre colonnes restent
visuellement concordantes aux sept points de contrôle. Les mouvements de cadrage
2D sont visibles, le gros plan conserve l’œuvre, la scène 3D présente le tableau
dans la pièce avec lumière et perspective, le match superpose progressivement la
scène au cadre réel, puis la photo finale reste nette. Aucune frame noire, aucun
diagnostic de média manquant et aucun artefact de rupture n’a été observé.

Les preuves reproductibles sont générées dans `dist/v3-qualification` ; ce dossier
reste un artefact de release local et n’est pas versionné.
