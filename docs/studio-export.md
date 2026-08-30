# Export final du Studio

Le Studio exporte localement le `StudioProject` courant avec le même
`StudioRenderSession` que l’aperçu. Le chemin final ne contient donc aucune version
parallèle des caméras, effets 2D, scènes 3D, médias réels ou transitions.

## Parcours utilisateur

L’onglet **Export** affiche la définition du projet, sa fréquence et le nombre exact
d’images. Les options persistées dans le document sont :

- MP4/H.264, format principal prêt à partager ;
- MOV/H.264 ou WebM/VP9 lorsque ce conteneur est requis ;
- profil Studio ou Rapide ;
- musique **Référence**, qui conserve le montage mais produit une vidéo seule ;
- musique **Intégrée**, mixée localement puis encodée en AAC ou Opus ;
- CRF de 0 à 51.

La fréquence de sortie est l’horloge du projet : 30 ou 60 FPS. Un projet standard
conserve le preset vertical 1080 × 1920. Modifier un conteneur ou la qualité est une
édition annulable du document. La politique audio l’est également ; choisir une
destination ne modifie pas le montage.

## Exécution et sûreté

Le contrôleur desktop travaille hors du thread de l’interface et publie la progression
en images terminées. La capture 3D reste effectuée sur le thread Qt par le pont local
déjà employé pour les proxies. Le bouton **Annuler** interrompt les sources coûteuses
et l’encodeur à la prochaine limite sûre.

En mode Référence, FFmpeg écrit dans `<nom>.part.<extension>`. En mode Intégré, la
vidéo, le PCM 48 kHz stéréo et le mux sont trois intermédiaires distincts. Le mix suit
les trims, silences, fades, gains de clips, gains de pistes et le plafond limiteur sur
les mêmes frontières de frames que le monitoring. La vidéo est copiée dans le mux sans
réencodage. Le fichier final est remplacé uniquement après le succès de toutes les
étapes. Une erreur ou une annulation supprime chaque intermédiaire et conserve donc un
ancien export valide, octet pour octet.

Les MP4 et MOV reçoivent `faststart` et les métadonnées BT.709. Toutes les sorties
utilisent des dimensions paires et du YUV 4:2:0 pour rester lisibles dans le lecteur
local et sur les plateformes sociales courantes.

La bande PCM couvre exactement la durée du projet. Les zones sans clip et la fin d’une
piste courte sont silencieuses. Un média audio manquant bloque l’export intégré avec un
diagnostic ; le mode Référence reste exportable puisqu’il ne consomme pas le fichier
audio.
