"""Formatage des nombres, montants, dates et unités à la française."""

from __future__ import annotations

from datetime import date

from copilote.analyses import JourSemaine


def euros(montant: float) -> str:
    """« 1 234,56 € »"""
    texte = f"{montant:,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"


def nombre(x: float) -> str:
    """« 2 », « 2,5 »"""
    return f"{x:g}".replace(".", ",")


def quantite(x: float, unite: str) -> str:
    """« 2 cartons », « 1 seau », « 6 kg », « 3 plateaux »."""
    if x >= 2 and unite not in ("kg", "L") and not unite.endswith(("s", "x")):
        unite += "x" if unite.endswith("eau") else "s"
    return f"{nombre(x)} {unite}"


def jours(n: float) -> str:
    """Pour « tous les … » : « jours » (n = 1) ou « 7 jours »."""
    return "jours" if n == 1 else f"{nombre(n)} jours"


def date_courte(d: date) -> str:
    return d.strftime("%d/%m")


def date_longue(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def jour_et_date(d: date) -> str:
    """« vendredi 30/10 »"""
    return f"{JourSemaine.de(d)} {date_courte(d)}"


def liste(elements: list[str]) -> str:
    """« a », « a et b », « a, b et c »"""
    if len(elements) <= 1:
        return "".join(elements)
    return ", ".join(elements[:-1]) + " et " + elements[-1]


def minuscule_initiale(libelle: str) -> str:
    """Pour insérer un libellé dans une phrase : « Sorbet citron » -> « sorbet citron »."""
    return libelle[:1].lower() + libelle[1:]


def pluriel(n: int, singulier: str, pluriel_: str | None = None) -> str:
    return f"{n} {singulier if n <= 1 else (pluriel_ or singulier + 's')}"
