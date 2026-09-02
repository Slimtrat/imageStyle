# Régions sémantiques du Studio

Une région sémantique désigne un élément de l’œuvre dans son espace canonique : un
œil, une bouche, un personnage, une fleur ou une forme libre. Elle ne dépend ni du
moteur qui l’a proposée, ni du plan sur lequel elle sera animée.

## Contrat de produit

Une région persistée contient toujours :

- un identifiant et un type sémantique ;
- un cadrage normalisé dans l’œuvre source ;
- un masque canonique portable ;
- des affordances, par exemple `blinkable` ;
- la provenance de l’analyse et sa version ;
- les informations nécessaires pour la corriger manuellement.

Les animations consomment uniquement ce contrat. Le blink, la sortie de cadre ou une
future déformation ne doivent donc jamais appeler directement un détecteur.

## Stratégie de détection

Le chemin recommandé est hybride :

1. des primitives locales déterministes proposent rapidement des composantes à partir
   des contours, contrastes, couleurs et régions connexes ;
2. un analyseur sémantique local optionnel attribue des catégories et affine les
   masques lorsque l’image est figurative ;
3. l’utilisateur confirme, renomme ou corrige les propositions ;
4. le Studio fige le résultat en masque canonique portable dans le projet.

Cette séparation répond à deux réalités des œuvres : un contour très net n’est pas
forcément un objet, et un objet peint peut traverser plusieurs aplats sans contour
fermé. Aucun moteur unique ne doit être considéré comme vérité.

Le port Python `SemanticRegionDetector` accepte l’image canonique et retourne des
`SemanticRegionCandidate` neutres. Plusieurs implémentations pourront être comparées
avec les mêmes critères sans modifier les recettes ou le compositeur :

- fidélité du masque aux bords peints ;
- stabilité sur œuvres abstraites et figuratives ;
- coût mémoire et temps d’analyse hors ligne ;
- reproductibilité et poids dans l’EXE ;
- possibilité de proposer plusieurs candidats plutôt que d’imposer un résultat.

## Slice actuelle

La V3 accepte une région manuelle fiable dans `semantic_regions`, génère ou importe son
masque, enregistre la provenance `manual.recipe-regions`, puis reprojette ce même masque
sur la photo réelle — ou depuis la frame vidéo de référence — avec l’homographie
persistée du raccord spatial. Une correction par poignée remplace cette matrice pour le
raccord et la projection dans le même commit. `region.blink` peut ainsi s’exécuter à la
fin du plan réel tout en suivant son animation de caméra.

Pour une région œil, le contrat conserve aussi une géométrie de paupière indépendante
du timing de l’action : axe local, courbure, amplitude, zone de protection de la matière
et largeur du trait fermé. Le renderer prélève la couleur dominante du visage, conserve
sa microtexture et déplace deux fronts de paupière vers l’axe. Il ne rebouche plus l’œil
par inpainting et ne réduit plus sa texture en bande. Une planche headless 2×4 compare
automatiquement les quatre états dans l’œuvre canonique et dans la photo réelle.

## Propositions automatiques locales

`LocalInterestRegionDetector` implémente le port neutre
`SemanticRegionDetector`. L’analyse combine cinq indices sans réseau : contraste
local, densité de contours, couleur distinctive, visage frontal probable et centre de
composition. Elle ne nomme donc jamais arbitrairement un objet qu’elle ne sait pas
reconnaître. Sur une œuvre uniforme ou trop peu structurée, elle produit uniquement
une région de composition centrale explicitement marquée comme repli.

Le classement est déterministe. Chaque proposition contient :

- des coordonnées normalisées dans le repère canonique de l’œuvre ;
- un masque PNG local, référencé comme asset plutôt qu’encodé dans le projet ;
- un rang, une confiance et la raison principale de la proposition ;
- les sous-scores `contrast`, `edge_density`, `color_saliency` et
  `centrality` ;
- les affordances `camera-inspectable` et `mask-animatable`.

La sélection finale limite le recouvrement entre régions et commence par diversifier
les raisons. Le Studio affiche toutes les propositions sur le canvas, puis détaille le
score de la région sélectionnée. Une proposition peut être renommée, recadrée ou
ignorée avec les mêmes commandes annulables que les régions manuelles.

Le détecteur est exécuté par l’analyseur de scène existant : worker unique annulable,
cache indexé par empreinte de l’œuvre et version d’analyse, écritures atomiques, puis
provenance persistée dans le projet. Une nouvelle analyse remplace seulement les faits
appartenant à l’analyseur ; les régions manuelles restent intactes. Les pixels, masques
et métadonnées ne quittent jamais la machine.
