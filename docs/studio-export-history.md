# Historique des Reels Studio

La banque locale de générations utilise désormais le manifeste `history.json` en
version 2. Les manifests version 1 restent lisibles et sont convertis uniquement lors
de la prochaine écriture ; aucune ancienne entrée n’est supprimée pendant la lecture.

Une entrée Studio est créée seulement après le signal de succès de l’export atomique.
Elle contient :

- le type `studio`, distinct des exports Atelier 2D et Studio 3D ;
- le chemin du Reel et celui de l’œuvre source ;
- l’identifiant du `StudioProject` et le chemin du fichier `.artanimate` lorsqu’il a
  déjà été enregistré ;
- la définition, les FPS, le nombre d’images, le conteneur, la qualité et la politique
  audio ;
- une vignette JPEG locale décodée sur la frame centrale du Reel par le lecteur vidéo
  du client.

Une nouvelle réussite vers la même destination remplace l’entrée et sa vignette au lieu
de créer un doublon. Une annulation, une erreur de rendu ou un échec de mux n’émet pas
le signal de succès et ne peut donc pas polluer la banque.

Les cartes réutilisent les actions **Lire** et **Afficher dans l’Explorateur Windows**.
Une entrée liée propose aussi **Ouvrir le projet Studio**. Un Reel ou un projet déplacé
reste visible avec un diagnostic et les actions impossibles sont désactivées.

L’historique ne possède jamais le projet ni les médias : retirer une entrée efface
uniquement sa vignette en cache. La suppression confirmée de la vidéo cible uniquement
le chemin de sortie. Pour les entrées Studio, le manifeste conserve également la liste
des chemins protégés connus ; une entrée incohérente pointant vers l’œuvre, un média ou
le projet est retirée sans supprimer ce fichier.
