"""Génère le jeu de données fictif utilisé par la source `mock`.

Le script est déterministe (graine fixe) : relancé, il produit exactement le même
fichier. Les données sont inventées mais construites pour être crédibles :

- 30 clients de types variés (restaurants, cantines, boulangeries, EHPAD…) ;
- 80 produits frais et surgelés avec prix, unités et durées de vie réalistes ;
- 6 mois de commandes : chaque client a ses jours de commande, ses produits
  habituels, ses quantités types, une saisonnalité (glaces l'été, cantines
  fermées en juillet-août) et parfois des produits qu'il a cessé de commander
  récemment (« décrochage ») ;
- un stock détaillé par lot avec DLC, dont des lots proches de la péremption
  et des produits en surstock.

Usage :
    python -m scripts.generer_donnees_mock            # écrit copilote/datahub/donnees/mock_data.json
    python -m scripts.generer_donnees_mock --graine 7 --sortie /tmp/autre.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from pydantic import JsonValue

from copilote.domaine import Client, Commande, Famille, LigneCommande, Lot, Produit

GRAINE = 42
DATE_REFERENCE = date(2026, 10, 23)  # « aujourd'hui » dans le jeu de données (un vendredi)
NB_JOURS_HISTORIQUE = 183  # environ 6 mois
SORTIE_PAR_DEFAUT = Path(__file__).resolve().parent.parent / "copilote" / "datahub" / "donnees" / "mock_data.json"

# ---------------------------------------------------------------------------
# Catalogue : (code, libellé, catégorie, unité, prix HT, durée de vie en jours, cibles)
# Les « cibles » indiquent quels types de clients achètent typiquement le produit :
#   R = restaurant/brasserie, P = pizzeria, C = cantine/EHPAD, B = boulangerie,
#   T = traiteur, H = hôtel, S = snack
# ---------------------------------------------------------------------------

PRODUITS_FRAIS = [
    # Crèmerie
    ("FR001", "Beurre doux AOP 1 kg", "Crèmerie", "kg", 9.80, 60, "RPCBTH"),
    ("FR002", "Beurre de tourage 82 % 2 kg", "Crèmerie", "plaque", 18.50, 60, "B"),
    ("FR003", "Crème fraîche épaisse 30 % 5 L", "Crèmerie", "seau", 24.90, 25, "RCBTH"),
    ("FR004", "Crème liquide 35 % 1 L", "Crèmerie", "brique", 4.60, 30, "RPBT"),
    ("FR005", "Lait entier 1 L", "Crèmerie", "brique", 1.10, 30, "CBH"),
    ("FR006", "Œufs frais calibre M, plateau de 30", "Crèmerie", "plateau", 7.40, 28, "RCBTHS"),
    ("FR007", "Mozzarella fior di latte 1 kg", "Crèmerie", "kg", 9.90, 18, "PRS"),
    ("FR008", "Emmental râpé 1 kg", "Crèmerie", "sachet", 8.20, 30, "RPCBS"),
    ("FR009", "Comté 12 mois 1 kg", "Crèmerie", "kg", 17.50, 45, "RTH"),
    ("FR010", "Fromage blanc 20 % 5 kg", "Crèmerie", "seau", 14.80, 20, "CH"),
    ("FR011", "Yaourt nature, carton de 48", "Crèmerie", "carton", 11.50, 25, "CH"),
    ("FR012", "Mascarpone 500 g", "Crèmerie", "pot", 4.20, 30, "PRT"),
    ("FR013", "Parmigiano Reggiano 1 kg", "Crèmerie", "kg", 21.00, 60, "PR"),
    ("FR014", "Bûche de chèvre 1 kg", "Crèmerie", "kg", 12.40, 25, "RTS"),
    # Boucherie
    ("FR015", "Entrecôte de bœuf VBF", "Boucherie", "kg", 28.50, 10, "RT"),
    ("FR016", "Bavette d'aloyau", "Boucherie", "kg", 19.80, 10, "RS"),
    ("FR017", "Steak haché frais 15 %, boîte de 10", "Boucherie", "boîte", 11.90, 6, "RCS"),
    ("FR018", "Sauté de veau", "Boucherie", "kg", 16.40, 8, "RCT"),
    ("FR019", "Épaule d'agneau", "Boucherie", "kg", 14.90, 10, "RT"),
    ("FR020", "Filet mignon de porc", "Boucherie", "kg", 13.20, 9, "RTC"),
    ("FR021", "Échine de porc", "Boucherie", "kg", 7.80, 9, "RC"),
    # Volaille
    ("FR022", "Filet de poulet Label Rouge", "Volaille", "kg", 13.90, 8, "RCTS"),
    ("FR023", "Cuisse de poulet", "Volaille", "kg", 5.40, 8, "C"),
    ("FR024", "Magret de canard", "Volaille", "kg", 18.90, 12, "RT"),
    ("FR025", "Escalope de dinde", "Volaille", "kg", 10.50, 8, "CS"),
    # Charcuterie
    ("FR026", "Jambon blanc supérieur", "Charcuterie", "kg", 11.20, 15, "PCBHS"),
    ("FR027", "Jambon cru 18 mois", "Charcuterie", "kg", 19.50, 40, "PRTH"),
    ("FR028", "Lardons fumés 1 kg", "Charcuterie", "sachet", 7.40, 25, "RPCT"),
    ("FR029", "Chorizo tranché 500 g", "Charcuterie", "sachet", 6.90, 35, "PS"),
    ("FR030", "Saucisse de Toulouse", "Charcuterie", "kg", 8.60, 10, "RC"),
    # Marée
    ("FR031", "Pavé de saumon", "Marée", "kg", 22.90, 5, "RTH"),
    ("FR032", "Dos de cabillaud", "Marée", "kg", 24.50, 5, "RT"),
    ("FR033", "Filet de lieu noir", "Marée", "kg", 15.80, 5, "RC"),
    ("FR034", "Crevettes cuites", "Marée", "kg", 17.90, 6, "RT"),
    # Fruits et légumes
    ("FR035", "Mélange de salades 4e gamme 1 kg", "Fruits et légumes", "sachet", 6.20, 6, "RPCTHS"),
    ("FR036", "Tomates grappe", "Fruits et légumes", "kg", 3.40, 8, "RPCTS"),
    ("FR037", "Pommes de terre, sac de 10 kg", "Fruits et légumes", "sac", 8.90, 30, "RC"),
    ("FR038", "Oignons jaunes, filet de 5 kg", "Fruits et légumes", "filet", 5.20, 40, "RPCT"),
    ("FR039", "Champignons de Paris", "Fruits et légumes", "kg", 4.80, 6, "RPT"),
    ("FR040", "Citrons", "Fruits et légumes", "kg", 3.10, 20, "RTH"),
    ("FR041", "Pommes Golden", "Fruits et légumes", "kg", 2.40, 25, "CBH"),
    # Traiteur frais
    ("FR042", "Pâte feuilletée pur beurre 5 kg", "Traiteur frais", "carton", 16.40, 20, "BT"),
    ("FR043", "Tagliatelles fraîches 1 kg", "Traiteur frais", "sachet", 5.90, 20, "RPT"),
    ("FR044", "Houmous 1 kg", "Traiteur frais", "pot", 7.20, 15, "TS"),
    ("FR045", "Taboulé oriental 2 kg", "Traiteur frais", "barquette", 9.80, 8, "TCS"),
]

PRODUITS_SURGELES = [
    # Viennoiserie et boulangerie
    ("SG001", "Croissant pur beurre cru 60 g, carton de 150", "Viennoiserie surgelée", "carton", 49.00, 365, "BH"),
    ("SG002", "Pain au chocolat cru 70 g, carton de 140", "Viennoiserie surgelée", "carton", 52.00, 365, "BH"),
    ("SG003", "Pain aux raisins cru, carton de 100", "Viennoiserie surgelée", "carton", 44.00, 365, "BH"),
    ("SG004", "Chausson aux pommes cru, carton de 100", "Viennoiserie surgelée", "carton", 41.00, 365, "BH"),
    ("SG005", "Baguette précuite 280 g, carton de 50", "Pain surgelé", "carton", 22.50, 270, "RCHS"),
    ("SG006", "Pain burger brioché, carton de 48", "Pain surgelé", "carton", 18.90, 270, "RS"),
    ("SG007", "Mini-pains assortis, carton de 200", "Pain surgelé", "carton", 29.90, 270, "RTH"),
    ("SG008", "Pâton à pizza 250 g, carton de 40", "Pain surgelé", "carton", 21.00, 270, "P"),
    # Légumes
    ("SG009", "Haricots verts extra-fins 2,5 kg", "Légumes surgelés", "sachet", 7.90, 540, "RCT"),
    ("SG010", "Petits pois 2,5 kg", "Légumes surgelés", "sachet", 6.40, 540, "C"),
    ("SG011", "Poêlée méridionale 2,5 kg", "Légumes surgelés", "sachet", 9.20, 540, "RC"),
    ("SG012", "Épinards hachés 2,5 kg", "Légumes surgelés", "sachet", 6.80, 540, "C"),
    ("SG013", "Brocolis en fleurettes 2,5 kg", "Légumes surgelés", "sachet", 8.10, 540, "C"),
    ("SG014", "Ratatouille cuisinée 2,5 kg", "Légumes surgelés", "sachet", 11.40, 540, "CT"),
    ("SG015", "Oignons émincés 2,5 kg", "Légumes surgelés", "sachet", 5.40, 540, "RPCS"),
    ("SG016", "Persil ciselé 500 g", "Légumes surgelés", "sachet", 4.90, 540, "RT"),
    # Pommes de terre
    ("SG017", "Frites 10 mm, carton 4 × 2,5 kg", "Pommes de terre surgelées", "carton", 16.80, 540, "RCS"),
    ("SG018", "Potatoes épicées 2,5 kg", "Pommes de terre surgelées", "sachet", 7.90, 540, "S"),
    ("SG019", "Pommes noisettes 2,5 kg", "Pommes de terre surgelées", "sachet", 8.40, 540, "C"),
    # Marée surgelée
    ("SG020", "Filet de colin pané, carton de 50", "Marée surgelée", "carton", 34.00, 540, "C"),
    ("SG021", "Pavé de saumon surgelé 5 kg", "Marée surgelée", "carton", 59.00, 540, "RC"),
    ("SG022", "Crevettes crues décortiquées 1 kg", "Marée surgelée", "sachet", 14.90, 540, "RT"),
    ("SG023", "Calamars à la romaine 1 kg", "Marée surgelée", "sachet", 9.80, 540, "RPS"),
    # Viandes surgelées
    ("SG024", "Steak haché 15 % surgelé, carton de 40", "Viandes surgelées", "carton", 32.00, 365, "CS"),
    ("SG025", "Nuggets de poulet 1 kg", "Viandes surgelées", "sachet", 8.90, 365, "CS"),
    ("SG026", "Cordon bleu de volaille, carton de 40", "Viandes surgelées", "carton", 29.00, 365, "C"),
    ("SG027", "Boulettes de bœuf 2 kg", "Viandes surgelées", "sachet", 15.60, 365, "CS"),
    # Desserts et glaces
    ("SG028", "Glace vanille 5 L", "Desserts et glaces", "bac", 19.50, 540, "RPCHS"),
    ("SG029", "Sorbet citron 2,5 L", "Desserts et glaces", "bac", 12.80, 540, "RPH"),
    ("SG030", "Fondant au chocolat, carton de 24", "Desserts et glaces", "carton", 26.40, 365, "RPS"),
    ("SG031", "Tarte aux pommes 10 parts", "Desserts et glaces", "pièce", 13.90, 365, "RCH"),
    ("SG032", "Mélange de fruits rouges 1 kg", "Desserts et glaces", "sachet", 9.60, 540, "BRT"),
    ("SG033", "Profiteroles, carton de 60", "Desserts et glaces", "carton", 18.50, 365, "RT"),
    # Plats et entrées
    ("SG034", "Mini-quiches assorties, carton de 60", "Plats et entrées surgelés", "carton", 17.50, 365, "TBH"),
    ("SG035", "Lasagnes bolognaise 3 kg", "Plats et entrées surgelés", "barquette", 18.90, 365, "CS"),
]

PRODUITS_SAISONNIERS_ETE = {"SG028", "SG029"}  # glaces et sorbets : forte demande l'été

# ---------------------------------------------------------------------------
# Clients : (nom, type, lettre de cible, ville, contact)
# ---------------------------------------------------------------------------

CLIENTS = [
    ("Le Bouchon des Canuts", "Restaurant", "R", "Lyon 4e", "Mme Girard"),
    ("La Table de Marius", "Restaurant", "R", "Villeurbanne", "M. Fabre"),
    ("Au Petit Comptoir", "Restaurant", "R", "Caluire-et-Cuire", "M. Lambert"),
    ("L'Atelier Gourmand", "Restaurant", "R", "Écully", "Mme Rousseau"),
    ("Chez Lucette", "Restaurant", "R", "Bron", "Mme Perrin"),
    ("Brasserie du Parc", "Brasserie", "R", "Lyon 6e", "M. Morel"),
    ("Brasserie de la Gare", "Brasserie", "R", "Vénissieux", "M. Garnier"),
    ("Le Grand Café des Halles", "Brasserie", "R", "Lyon 3e", "Mme Faure"),
    ("Pizzeria Bella Napoli", "Pizzeria", "P", "Vaulx-en-Velin", "M. Russo"),
    ("Pizza Momo", "Pizzeria", "P", "Saint-Priest", "M. Benali"),
    ("Il Forno di Gino", "Pizzeria", "P", "Lyon 7e", "M. Esposito"),
    ("Groupe scolaire Jean-Moulin", "Cantine scolaire", "C", "Villeurbanne", "Mme Chevalier"),
    ("Cuisine centrale de Bron", "Cantine scolaire", "C", "Bron", "M. Robin"),
    ("Collège Les Tilleuls", "Cantine scolaire", "C", "Décines-Charpieu", "Mme Masson"),
    ("Lycée Ampère - restauration", "Cantine scolaire", "C", "Lyon 2e", "M. Henry"),
    ("École Sainte-Marie", "Cantine scolaire", "C", "Oullins", "Mme Blanc"),
    ("EHPAD Les Glycines", "EHPAD", "C", "Tassin-la-Demi-Lune", "Mme Gauthier"),
    ("Résidence Le Bel Âge", "EHPAD", "C", "Rillieux-la-Pape", "M. Mercier"),
    ("EHPAD Saint-Joseph", "EHPAD", "C", "Meyzieu", "Mme Bonnet"),
    ("Boulangerie Martin", "Boulangerie-pâtisserie", "B", "Lyon 5e", "M. Martin"),
    ("Au Fournil de Léa", "Boulangerie-pâtisserie", "B", "Villeurbanne", "Mme Dupuis"),
    ("La Mie Dorée", "Boulangerie-pâtisserie", "B", "Sainte-Foy-lès-Lyon", "M. Leroy"),
    ("Maison Pétrin", "Boulangerie-pâtisserie", "B", "Craponne", "Mme Arnaud"),
    ("Boulangerie des Pentes", "Boulangerie-pâtisserie", "B", "Lyon 1er", "M. Roche"),
    ("Traiteur Saveurs & Fêtes", "Traiteur", "T", "Champagne-au-Mont-d'Or", "Mme Vidal"),
    ("Délices de Margaux", "Traiteur", "T", "Lyon 8e", "Mme Lemoine"),
    ("Hôtel des Brotteaux", "Hôtel", "H", "Lyon 6e", "M. Fontaine"),
    ("Hôtel Le Confluent", "Hôtel", "H", "Lyon 2e", "Mme Picard"),
    ("Snack Le Bon Coin", "Snack", "S", "Vénissieux", "M. Haddad"),
    ("Burger Street", "Snack", "S", "Villeurbanne", "M. Nguyen"),
]

TELEVENDEURS = ["Julie Moreau", "Karim Bensaïd", "Sophie Lefèvre"]

# Rythme de commande par type : jours de la semaine possibles (0 = lundi) et
# nombre de jours de commande par semaine (min, max)
RYTHMES = {
    "R": ([0, 1, 2, 3, 4], (2, 3)),
    "P": ([1, 2, 3, 4], (1, 2)),
    "C": ([0, 3], (2, 2)),
    "B": ([0, 1, 2, 3, 4, 5], (2, 3)),
    "T": ([1, 2, 3], (1, 1)),
    "H": ([0, 3], (1, 2)),
    "S": ([0, 1, 3], (1, 2)),
}

# Quantité de base par unité (pour un client « moyen » et une livraison)
QUANTITE_BASE: dict[str, int] = {
    "kg": 6,
    "plaque": 4,
    "seau": 2,
    "brique": 12,
    "plateau": 6,
    "sachet": 4,
    "pot": 4,
    "boîte": 4,
    "sac": 3,
    "filet": 2,
    "carton": 2,
    "barquette": 3,
    "bac": 2,
    "pièce": 4,
}


def _est_vacances_ete(jour: date) -> bool:
    return date(jour.year, 7, 4) <= jour <= date(jour.year, 8, 31)


@dataclass(frozen=True)
class HabitudeProduit:
    proba: float  # probabilité de figurer dans une commande
    quantite: float  # quantité typique


@dataclass
class ProfilClient:
    jours: list[int]
    produits: dict[str, HabitudeProduit]
    volume: float
    tendance: float  # évolution du volume sur 6 mois
    arrets: dict[str, date] = field(default_factory=dict)  # produits « décrochés » et date d'arrêt


@dataclass(frozen=True)
class JeuDeDonnees:
    graine: int
    debut: date
    clients: list[Client]
    produits: list[Produit]
    commandes: list[Commande]
    lots: list[Lot]

    def vers_json(self) -> dict[str, JsonValue]:
        return {
            "meta": {
                "description": "Jeu de données FICTIF pour la démo du copilote télévente",
                "graine": self.graine,
                "date_reference": DATE_REFERENCE.isoformat(),
                "date_debut_historique": self.debut.isoformat(),
            },
            "clients": [c.model_dump(mode="json") for c in self.clients],
            "produits": [p.model_dump(mode="json") for p in self.produits],
            "commandes": [c.model_dump(mode="json", exclude={"montant_ht"}) for c in self.commandes],
            "lots": [l.model_dump(mode="json") for l in self.lots],
        }


def _produits() -> tuple[list[Produit], dict[str, str]]:
    produits: list[Produit] = []
    cibles_par_produit: dict[str, str] = {}
    for liste, famille in ((PRODUITS_FRAIS, Famille.FRAIS), (PRODUITS_SURGELES, Famille.SURGELE)):
        for code, libelle, categorie, unite, prix, duree_vie, cibles in liste:
            produits.append(
                Produit(
                    code=code,
                    libelle=libelle,
                    categorie=categorie,
                    famille=famille,
                    unite=unite,
                    prix_unitaire_ht=prix,
                    duree_vie_jours=duree_vie,
                )
            )
            cibles_par_produit[code] = cibles
    return produits, cibles_par_produit


def _clients(
    rng: random.Random, cibles_par_produit: dict[str, str], unites: dict[str, str]
) -> tuple[list[Client], dict[str, ProfilClient]]:
    clients: list[Client] = []
    profils: dict[str, ProfilClient] = {}
    for i, (nom, type_, cible, ville, contact) in enumerate(CLIENTS, start=1):
        client_id = f"C{i:03d}"
        clients.append(
            Client(
                id=client_id,
                nom=nom,
                type=type_,
                ville=ville,
                contact=contact,
                telephone=f"04 78 {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                commercial=TELEVENDEURS[i % len(TELEVENDEURS)],
            )
        )

        candidats = [c for c, cibles in cibles_par_produit.items() if cible in cibles]
        autres = [c for c in cibles_par_produit if c not in candidats]
        jours_possibles, (nb_min, nb_max) = RYTHMES[cible]
        jours_commande = sorted(rng.sample(jours_possibles, rng.randint(nb_min, nb_max)))

        habituels = rng.sample(candidats, min(len(candidats), rng.randint(8, 15)))
        occasionnels = [c for c in candidats if c not in habituels]
        # Un ou deux produits hors cible, commandés très rarement (variété réaliste)
        hors_cible = rng.sample(autres, 2)

        produits_client: dict[str, HabitudeProduit] = {}
        for code in habituels:
            produits_client[code] = HabitudeProduit(
                proba=round(rng.uniform(0.45, 0.95), 2),
                quantite=QUANTITE_BASE[unites[code]] * rng.uniform(0.6, 1.6),
            )
        for code in occasionnels:
            produits_client[code] = HabitudeProduit(
                proba=round(rng.uniform(0.02, 0.10), 2),
                quantite=QUANTITE_BASE[unites[code]] * rng.uniform(0.5, 1.0),
            )
        for code in hors_cible:
            produits_client[code] = HabitudeProduit(proba=0.02, quantite=QUANTITE_BASE[unites[code]] * 0.5)

        # Décrochage : pour ~40 % des clients, 1 ou 2 produits habituels importants
        # ne sont plus commandés depuis 3 à 5 semaines (concurrent ? changement de carte ?)
        arrets: dict[str, date] = {}
        if rng.random() < 0.4:
            importants = [c for c in habituels if produits_client[c].proba >= 0.6]
            for code in rng.sample(importants, min(len(importants), rng.randint(1, 2))):
                arrets[code] = DATE_REFERENCE - timedelta(days=rng.randint(21, 35))

        profils[client_id] = ProfilClient(
            jours=jours_commande,
            produits=produits_client,
            volume=rng.uniform(0.7, 1.8) * (1.8 if type_ == "Cantine scolaire" and "centrale" in nom else 1.0),
            tendance=rng.choice([-0.25, -0.1, 0.0, 0.0, 0.1, 0.2]),
            arrets=arrets,
        )
    return clients, profils


def _commandes(
    rng: random.Random, debut: date, clients: list[Client], profils: dict[str, ProfilClient], prix: dict[str, float]
) -> list[Commande]:
    commandes: list[Commande] = []
    jour = debut
    while jour < DATE_REFERENCE:  # les commandes du jour ne sont pas encore passées
        for client in clients:
            profil = profils[client.id]
            if jour.weekday() not in profil.jours:
                continue
            if client.type == "Cantine scolaire" and _est_vacances_ete(jour):
                continue
            if rng.random() < 0.08:  # commande sautée (fermeture, oubli…)
                continue
            avancement = (jour - debut).days / NB_JOURS_HISTORIQUE
            facteur_volume = profil.volume * (1 + profil.tendance * avancement)
            ete = jour.month in (6, 7, 8)

            lignes: list[LigneCommande] = []
            for code, habitude in profil.produits.items():
                arret = profil.arrets.get(code)
                if arret and jour >= arret:
                    continue
                proba = habitude.proba
                if code in PRODUITS_SAISONNIERS_ETE:
                    proba = min(0.95, proba * 1.8) if ete else proba * 0.5
                if rng.random() > proba:
                    continue
                quantite = max(1, round(rng.gauss(habitude.quantite, habitude.quantite * 0.2) * facteur_volume))
                lignes.append(LigneCommande(produit_code=code, quantite=quantite, prix_unitaire_ht=prix[code]))
            if lignes:
                commandes.append(
                    Commande(id=f"CMD{len(commandes) + 1:06d}", client_id=client.id, date=jour, lignes=tuple(lignes))
                )
        jour += timedelta(days=1)
    return commandes


def _lots(rng: random.Random, produits: list[Produit], commandes: list[Commande]) -> list[Lot]:
    # Rotation : quantité vendue par jour sur les 4 dernières semaines
    ventes_28j: dict[str, float] = defaultdict(float)
    limite = DATE_REFERENCE - timedelta(days=28)
    for cmd in commandes:
        if cmd.date >= limite:
            for l in cmd.lignes:
                ventes_28j[l.produit_code] += l.quantite

    codes_frais = [p.code for p in produits if p.famille is Famille.FRAIS]
    codes_surgeles = [p.code for p in produits if p.famille is Famille.SURGELE]
    # Produits volontairement mis en difficulté pour la démo
    frais_dlc_courte = set(rng.sample(codes_frais, 11))
    surgeles_surstock = set(rng.sample(codes_surgeles, 6))
    surgeles_dlc_proche = set(rng.sample([c for c in codes_surgeles if c not in surgeles_surstock], 2))
    frais_surstock = set(rng.sample([c for c in codes_frais if c not in frais_dlc_courte], 3))

    lots: list[Lot] = []

    def ajouter_lot(produit: Produit, quantite: float, dlc: date, entrepot: str) -> None:
        lots.append(
            Lot(
                id=f"L{DATE_REFERENCE:%y%m}-{len(lots) + 1:04d}",
                produit_code=produit.code,
                quantite=max(1, round(quantite)),
                dlc=dlc,
                date_reception=min(DATE_REFERENCE, dlc - timedelta(days=produit.duree_vie_jours)),
                entrepot=entrepot,
            )
        )

    for p in produits:
        par_jour = ventes_28j[p.code] / 28
        if p.famille is Famille.FRAIS:
            couverture = 21 if p.code in frais_surstock else rng.uniform(4, 9)
            total = max(3, par_jour * couverture)
            nb_lots = rng.randint(1, 3)
            for k in range(nb_lots):
                # Même règle que l'analyse du stock : DLC courte = 30 % de la durée de vie (2 à 5 jours)
                seuil_dlc_courte = max(2, min(5, round(p.duree_vie_jours * 0.3)))
                if k == 0 and p.code in frais_dlc_courte:
                    dlc = DATE_REFERENCE + timedelta(days=rng.randint(1, seuil_dlc_courte))
                else:
                    dlc = DATE_REFERENCE + timedelta(days=rng.randint(seuil_dlc_courte + 1, p.duree_vie_jours + 1))
                ajouter_lot(p, total / nb_lots, dlc, "Entrepôt froid positif")
        else:
            couverture = rng.uniform(150, 220) if p.code in surgeles_surstock else rng.uniform(20, 45)
            total = max(5, par_jour * couverture)
            nb_lots = rng.randint(1, 2)
            for k in range(nb_lots):
                if k == 0 and p.code in surgeles_dlc_proche:
                    dlc = DATE_REFERENCE + timedelta(days=rng.randint(12, 28))
                else:
                    dlc = DATE_REFERENCE + timedelta(days=rng.randint(120, p.duree_vie_jours))
                ajouter_lot(p, total / nb_lots, dlc, "Chambre négative")
    return lots


def generer(graine: int = GRAINE) -> JeuDeDonnees:
    rng = random.Random(graine)
    debut = DATE_REFERENCE - timedelta(days=NB_JOURS_HISTORIQUE)
    produits, cibles_par_produit = _produits()
    clients, profils = _clients(rng, cibles_par_produit, {p.code: p.unite for p in produits})
    commandes = _commandes(rng, debut, clients, profils, {p.code: p.prix_unitaire_ht for p in produits})
    lots = _lots(rng, produits, commandes)
    return JeuDeDonnees(graine, debut, clients, produits, commandes, lots)


def ecrire(jeu: JeuDeDonnees, sortie: Path) -> None:
    """Une commande / un lot par ligne : fichier compact mais lisible et comparable (diff)."""
    donnees = jeu.vers_json()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    cles = ("clients", "produits", "commandes", "lots")
    with sortie.open("w", encoding="utf-8") as f:
        f.write("{\n")
        f.write(f'"meta": {json.dumps(donnees["meta"], ensure_ascii=False)},\n')
        for i, cle in enumerate(cles):
            elements = donnees[cle]
            assert isinstance(elements, list)
            f.write(f'"{cle}": [\n')
            f.write(",\n".join(json.dumps(x, ensure_ascii=False) for x in elements))
            f.write("\n]" + (",\n" if i < len(cles) - 1 else "\n"))
        f.write("}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graine", type=int, default=GRAINE)
    parser.add_argument("--sortie", type=Path, default=SORTIE_PAR_DEFAUT)
    args = parser.parse_args()
    jeu = generer(args.graine)
    ecrire(jeu, args.sortie)
    print(
        f"{len(jeu.clients)} clients, {len(jeu.produits)} produits, "
        f"{len(jeu.commandes)} commandes, {len(jeu.lots)} lots -> {args.sortie}"
    )


if __name__ == "__main__":
    main()
