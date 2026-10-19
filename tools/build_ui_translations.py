"""Rebuild the editor's complete eight-language interface dictionary."""
from __future__ import annotations

import ast
import json
from pathlib import Path


LANGS = ["de", "es", "fr", "it", "ja", "zh"]
ROWS = {
    "equipment": ["Ausrüstung", "Equipamiento", "Équipement", "Equipaggiamento", "装備", "装备"],
    "blessings": ["Segnungen", "Bendiciones", "Bénédictions", "Benedizioni", "祝福", "祝福"],
    "journey": ["Reise", "Viaje", "Voyage", "Viaggio", "旅", "旅程"],
    "character": ["Charakter", "Personaje", "Personnage", "Personaggio", "キャラクター", "角色"],
    "backups": ["Sicherungen", "Copias de seguridad", "Sauvegardes", "Backup", "バックアップ", "备份"],
    "open": ["Spielstand öffnen", "Abrir partida", "Ouvrir une sauvegarde", "Apri salvataggio", "セーブを開く", "打开存档"],
    "detect": ["Spielstände suchen", "Buscar partidas", "Chercher les sauvegardes", "Trova salvataggi", "セーブを検索", "查找存档"],
    "save": ["Spielstand aktualisieren", "Aplicar a la partida", "Appliquer à la sauvegarde", "Applica al salvataggio", "セーブに適用", "应用到存档"],
    "export": ["Kopie exportieren", "Exportar copia", "Exporter une copie", "Esporta copia", "コピーを書き出す", "导出副本"],
    "undo": ["Rückgängig", "Deshacer", "Annuler", "Annulla", "元に戻す", "撤销"],
    "redo": ["Wiederholen", "Rehacer", "Rétablir", "Ripeti", "やり直す", "重做"],
    "money": ["Münzen", "Monedas", "Pièces", "Monete", "コイン", "金币"],
    "souls": ["Seelen", "Almas", "Âmes", "Anime", "ソウル", "灵魂"],
    "prepare": ["Änderungen vorbereiten", "Preparar cambios", "Préparer les modifications", "Prepara modifiche", "変更を準備", "准备更改"],
    "prepared": ["Änderungen im Speicher vorbereitet.", "Cambios preparados en memoria.", "Modifications préparées en mémoire.", "Modifiche preparate in memoria.", "変更をメモリ上に準備しました。", "更改已在内存中准备就绪。"],
    "empty": ["Zum Beginnen einen Charakterspielstand öffnen", "Abre una partida de personaje para comenzar", "Ouvrez une sauvegarde de personnage pour commencer", "Apri un salvataggio del personaggio per iniziare", "キャラクターのセーブを開いて開始", "打开角色存档以开始"],
    "empty_note": ["Hier erscheinen dein Charakter, deine Ausrüstung und deine Reise.", "Aquí aparecerán tu personaje, equipamiento y viaje.", "Votre personnage, votre équipement et votre voyage apparaîtront ici.", "Qui appariranno il personaggio, l'equipaggiamento e il viaggio.", "キャラクター、装備、旅の進行状況がここに表示されます。", "角色、装备和旅程将显示在这里。"],
    "gear_title": ["DER NEPHILIM", "EL NEFILIM", "LE NEPHILIM", "IL NEPHILIM", "ネフィリム", "奈非天"],
    "gear_sub": ["Wähle einen Platz, um Ausrüstung anzusehen oder zu ersetzen.", "Selecciona una ranura para consultar o cambiar el equipo.", "Sélectionnez un emplacement pour examiner ou remplacer l'équipement.", "Seleziona uno spazio per esaminare o sostituire l'equipaggiamento.", "スロットを選んで装備の確認や交換ができます。", "选择栏位以查看或替换装备。"],
    "catalog": ["GEGENSTANDSKATALOG", "CATÁLOGO DE OBJETOS", "CATALOGUE D'OBJETS", "CATALOGO OGGETTI", "アイテム一覧", "物品目录"],
    "search": ["Nach Name oder Effekt suchen…", "Buscar por nombre o efecto…", "Chercher par nom ou effet…", "Cerca per nome o effetto…", "名前や効果で検索…", "按名称或效果搜索…"],
    "compare": ["VERGLEICH", "COMPARACIÓN", "COMPARAISON", "CONFRONTO", "比較", "比较"],
    "current": ["Aktuell", "Actual", "Actuel", "Attuale", "現在", "当前"],
    "selected": ["Ausgewählt", "Seleccionado", "Sélectionné", "Selezionato", "選択中", "已选择"],
    "attribute": ["Attribut", "Atributo", "Attribut", "Attributo", "能力値", "属性"],
    "delta": ["Unterschied", "Diferencia", "Différence", "Differenza", "差分", "差值"],
    "base_note": ["Basiswerte der Definition. Endwerte hängen von Qualität und Spielskalierung ab.", "Valores base de la definición. Las estadísticas finales dependen de la calidad y la escala del juego.", "Valeurs de base de la définition. Les statistiques finales dépendent de la qualité et de la progression du jeu.", "Valori base della definizione. Le statistiche finali dipendono dalla qualità e dalla scala del gioco.", "定義の基本値です。最終的な能力値は品質やゲーム内の補正で変わります。", "此处显示定义中的基础数值。最终属性取决于品质和游戏数值成长。"],
    "replace": ["Ausgewählten Gegenstand ersetzen", "Reemplazar objeto seleccionado", "Remplacer l'objet sélectionné", "Sostituisci oggetto selezionato", "選択したアイテムを交換", "替换所选物品"],
    "quality_only": ["Qualität ändern", "Cambiar calidad", "Changer la qualité", "Cambia qualità", "品質を変更", "更改品质"],
    "quality": ["Qualität", "Calidad", "Qualité", "Qualità", "品質", "品质"],
    "description": ["Beschreibung", "Descripción", "Description", "Descrizione", "説明", "描述"],
    "Head": ["Helm", "Casco", "Casque", "Elmo", "兜", "头盔"],
    "Body": ["Rüstung", "Armadura", "Armure", "Armatura", "鎧", "护甲"],
    "Legs": ["Beine", "Piernas", "Jambes", "Gambe", "脚", "腿部"],
    "Arms": ["Panzerhandschuhe", "Guanteletes", "Gantelets", "Guanti d'arme", "籠手", "护手"],
    "RightHand": ["Waffe", "Arma", "Arme", "Arma", "武器", "武器"],
    "LeftHand": ["Schild", "Escudo", "Bouclier", "Scudo", "盾", "盾牌"],
    "Trinket": ["Ring", "Anillo", "Anneau", "Anello", "指輪", "戒指"],
    "Amulet": ["Medaillon", "Medallón", "Médaillon", "Medaglione", "メダリオン", "吊坠"],
    "Common": ["Gewöhnlich", "Común", "Commun", "Comune", "コモン", "普通"],
    "Uncommon": ["Ungewöhnlich", "Poco común", "Peu commun", "Non comune", "アンコモン", "优秀"],
    "Rare": ["Selten", "Raro", "Rare", "Raro", "レア", "稀有"],
    "Epic": ["Episch", "Épico", "Épique", "Epico", "エピック", "史诗"],
    "Legendary": ["Legendär", "Legendario", "Légendaire", "Leggendario", "レジェンダリー", "传说"],
    "active_boons": ["DEINE SEGNUNGEN", "TUS BENDICIONES", "VOS BÉNÉDICTIONS", "LE TUE BENEDIZIONI", "獲得した祝福", "你的祝福"],
    "boon_sub": ["Bewege die Maus über ein Symbol, um den Effekt zu lesen. Wähle eine Segnung zum Hinzufügen oder Entfernen.", "Pasa el ratón sobre un icono para ver su efecto. Selecciona una bendición para añadirla o quitarla.", "Survolez une icône pour lire son effet. Sélectionnez une bénédiction à ajouter ou à retirer.", "Passa il mouse su un'icona per leggerne l'effetto. Seleziona una benedizione da aggiungere o rimuovere.", "アイコンにカーソルを合わせると効果を確認できます。追加または削除する祝福を選択してください。", "将鼠标悬停在图标上可查看效果。选择祝福以添加或移除。"],
    "boon_catalog": ["SEGNUNGSKATALOG", "CATÁLOGO DE BENDICIONES", "CATALOGUE DE BÉNÉDICTIONS", "CATALOGO BENEDIZIONI", "祝福一覧", "祝福目录"],
    "add_boon": ["Segnung hinzufügen", "Añadir bendición", "Ajouter une bénédiction", "Aggiungi benedizione", "祝福を追加", "添加祝福"],
    "remove_boon": ["Ausgewählte Segnung entfernen", "Quitar bendición seleccionada", "Retirer la bénédiction sélectionnée", "Rimuovi benedizione selezionata", "選択した祝福を削除", "移除所选祝福"],
    "gear_effect": ["Ausrüstungseffekt", "Efecto del equipo", "Effet de l'équipement", "Effetto dell'equipaggiamento", "装備の効果", "装备效果"],
    "run_effect": ["Reisesegnung", "Bendición del viaje", "Bénédiction du voyage", "Benedizione del viaggio", "旅の祝福", "旅程祝福"],
    "all": ["Alle", "Todas", "Toutes", "Tutte", "すべて", "全部"],
    "level": ["Stufe", "Nivel", "Niveau", "Livello", "レベル", "等级"],
    "stacks": ["Stapel", "Acumulaciones", "Cumuls", "Accumuli", "スタック", "层数"],
    "journey_title": ["WÄHLE DEINEN WEG", "ELIGE TU CAMINO", "CHOISISSEZ VOTRE VOIE", "SCEGLI IL TUO CAMMINO", "道を選ぶ", "选择你的道路"],
    "journey_sub": ["Ändere die gespeicherte Position in der manuellen Reise und die gewählte Schwierigkeit.", "Cambia la posición guardada del viaje manual y la dificultad seleccionada.", "Modifiez la position sauvegardée dans le voyage manuel et la difficulté choisie.", "Cambia la posizione salvata nel viaggio manuale e la difficoltà selezionata.", "手動の旅で保存された進行位置と選択した難易度を変更します。", "更改手动旅程中保存的进度位置和所选难度。"],
    "stage": ["Etappe", "Etapa", "Étape", "Tappa", "ステージ", "阶段"],
    "section": ["Abschnitt", "Sección", "Section", "Sezione", "区間", "关卡"],
    "difficulty": ["Schwierigkeit", "Dificultad", "Difficulté", "Difficoltà", "難易度", "难度"],
    "missions": ["Missionen in diesem Abschnitt", "Misiones disponibles en esta sección", "Missions proposées dans cette section", "Missioni disponibili in questa sezione", "この区間で選択できるミッション", "本关卡提供的任务"],
    "journey_note": ["Das Spiel nutzt diese gespeicherte Position beim Fortsetzen der Reise. Dein Charakter wird dadurch nicht innerhalb einer laufenden Mission teleportiert.", "El juego usa esta posición al continuar el viaje. Esto no teletransporta al personaje dentro de una misión activa.", "Le jeu utilise cette position lors de la reprise du voyage. Cela ne téléporte pas le personnage dans une mission en cours.", "Il gioco usa questa posizione quando riprendi il viaggio. Non teletrasporta il personaggio all'interno di una missione in corso.", "旅を再開すると、ゲームはこの保存位置を使用します。進行中のミッション内でキャラクターを移動させる機能ではありません。", "继续旅程时，游戏会使用此保存位置。此操作不会在正在进行的任务中传送角色。"],
    "character_title": ["CHARAKTER", "PERSONAJE", "PERSONNAGE", "PERSONAGGIO", "キャラクター", "角色"],
    "attributes": ["ATTRIBUTE", "ATRIBUTOS", "ATTRIBUTS", "ATTRIBUTI", "能力値", "属性"],
    "currency_title": ["MÜNZEN UND SEELEN", "MONEDAS Y ALMAS", "PIÈCES ET ÂMES", "MONETE E ANIME", "コインとソウル", "金币与灵魂"],
    "attribute_note": ["Attributänderungen berechnen EP, Stufe und ausgegebene Punkte nicht neu.", "Cambiar atributos no recalcula experiencia, nivel ni puntos gastados.", "La modification des attributs ne recalcule pas l'expérience, le niveau ou les points dépensés.", "La modifica degli attributi non ricalcola esperienza, livello o punti spesi.", "能力値を変更しても経験値、レベル、消費ポイントは再計算されません。", "更改属性不会重新计算经验、等级或已使用的点数。"],
    "backup_title": ["SICHERUNGSVERLAUF", "HISTORIAL DE COPIAS", "HISTORIQUE DES SAUVEGARDES", "CRONOLOGIA BACKUP", "バックアップ履歴", "备份历史"],
    "backup_sub": ["Vor jeder Übernahme oder Wiederherstellung wird automatisch eine geprüfte Sicherung erstellt.", "Se crea automáticamente una copia verificada antes de cada aplicación o restauración.", "Une copie vérifiée est créée automatiquement avant chaque application ou restauration.", "Un backup verificato viene creato automaticamente prima di ogni applicazione o ripristino.", "変更の適用や復元の前に、検証済みのバックアップを自動作成します。", "每次应用或恢复前都会自动创建经过验证的备份。"],
    "restore": ["Ausgewählte Sicherung wiederherstellen", "Restaurar copia seleccionada", "Restaurer la copie sélectionnée", "Ripristina backup selezionato", "選択したバックアップを復元", "恢复所选备份"],
    "folder": ["Sicherungsordner öffnen", "Abrir carpeta de copias", "Ouvrir le dossier des copies", "Apri cartella backup", "バックアップフォルダーを開く", "打开备份文件夹"],
    "no_backups": ["Für diesen Charakter gibt es noch keine Sicherungen.", "Este personaje aún no tiene copias de seguridad.", "Aucune copie pour ce personnage pour le moment.", "Nessun backup per questo personaggio.", "このキャラクターのバックアップはまだありません。", "此角色尚无备份。"],
    "ready": ["Spielstand geladen · keine ausstehenden Änderungen", "Partida cargada · sin cambios pendientes", "Sauvegarde chargée · aucune modification en attente", "Salvataggio caricato · nessuna modifica in sospeso", "セーブ読込済み · 未適用の変更なし", "存档已加载 · 无待应用更改"],
    "pending": ["ausstehende Änderungen", "cambios pendientes", "modifications en attente", "modifiche in sospeso", "未適用の変更", "待应用更改"],
    "close_game": ["Schließe das Spiel vor dem Übernehmen der Änderungen.", "Cierra el juego antes de aplicar los cambios.", "Fermez le jeu avant d'appliquer les modifications.", "Chiudi il gioco prima di applicare le modifiche.", "変更を適用する前にゲームを終了してください。", "应用更改前请关闭游戏。"],
    "discard": ["Änderungen verwerfen", "Descartar cambios", "Abandonner les modifications", "Scarta modifiche", "変更を破棄", "放弃更改"],
    "discard_question": ["Ausstehende Änderungen verwerfen?", "¿Descartar los cambios pendientes?", "Abandonner les modifications en attente ?", "Scartare le modifiche in sospeso?", "未適用の変更を破棄しますか？", "放弃待应用的更改？"],
    "review": ["Änderungen prüfen", "Revisar cambios", "Vérifier les modifications", "Rivedi modifiche", "変更を確認", "检查更改"],
    "apply_question": ["Diese Änderungen auf den Charakterspielstand anwenden? Zuvor wird eine Sicherung erstellt.", "¿Aplicar estos cambios a la partida del personaje? Primero se creará una copia de seguridad.", "Appliquer ces modifications à la sauvegarde du personnage ? Une copie sera créée auparavant.", "Applicare queste modifiche al salvataggio del personaggio? Prima verrà creato un backup.", "キャラクターのセーブに変更を適用しますか？ 最初にバックアップを作成します。", "将这些更改应用到角色存档？操作前将创建备份。"],
    "applied": ["Spielstand aktualisiert und geprüft. Das Original ist unter Sicherungen verfügbar.", "Partida actualizada y verificada. El original está disponible en Copias de seguridad.", "Sauvegarde modifiée et vérifiée. L'original est disponible dans Sauvegardes.", "Salvataggio aggiornato e verificato. L'originale è disponibile in Backup.", "セーブへの適用と検証が完了しました。元のデータはバックアップにあります。", "存档已应用并验证。原始存档可在备份中找到。"],
    "error": ["Aktion konnte nicht abgeschlossen werden", "No se pudo completar la acción", "Impossible de terminer l'action", "Impossibile completare l'azione", "操作を完了できませんでした", "无法完成操作"],
    "experimental": ["Experimentell · Spielstandversion 8", "Experimental · versión de partida 8", "Expérimental · version de sauvegarde 8", "Sperimentale · versione salvataggio 8", "試験版 · セーブバージョン8", "实验性 · 存档版本 8"],
    "no_item": ["Kein Gegenstand in diesem Platz", "No hay objeto en esta ranura", "Aucun objet dans cet emplacement", "Nessun oggetto in questo spazio", "このスロットにアイテムはありません", "此栏位没有物品"],
    "no_candidate": ["Wähle einen Gegenstand im Katalog", "Selecciona un objeto del catálogo", "Sélectionnez un objet du catalogue", "Seleziona un oggetto dal catalogo", "一覧からアイテムを選択", "在目录中选择物品"],
    "copy_saved": ["Geänderte Kopie und Originalsicherungen exportiert.", "Se exportaron la copia modificada y las copias de los originales.", "Copie modifiée et sauvegardes des originaux exportées.", "Copia modificata e backup degli originali esportati.", "変更済みコピーと元のバックアップを書き出しました。", "已导出修改后的副本和原始备份。"],
    "refresh": ["Neu laden", "Recargar", "Recharger", "Ricarica", "再読込", "重新加载"],
    "reserved": ["RUCKSACK / RESERVE", "MOCHILA / RESERVA", "SAC / RÉSERVE", "ZAINO / RISERVA", "バックパック / 予備", "背包 / 备用"],
    "select_existing": ["Wähle einen vorhandenen Rucksackgegenstand zum Ersetzen.", "Elige un objeto existente de la mochila para reemplazarlo.", "Choisissez un objet existant dans le sac à remplacer.", "Scegli un oggetto esistente nello zaino da sostituire.", "交換する既存のバックパック内アイテムを選択してください。", "选择背包中已有的物品进行替换。"],
    "about": ["ÜBER", "ACERCA DE", "À PROPOS", "INFORMAZIONI", "このアプリについて", "关于"],
    "effect": ["Effekt", "Efecto", "Effet", "Effetto", "効果", "效果"],
    "base_effect_note": ["Effekttext des Spiels; Zahlen für diese Qualität sind im Export nicht aufgelöst.", "Texto del juego; el material exportado no resuelve las cifras para esta calidad.", "Texte du jeu ; les valeurs de cette qualité ne sont pas résolues dans l'export.", "Testo del gioco; l'esportazione non risolve i valori per questa qualità.", "ゲーム内の基本説明です。この品質の数値はエクスポートデータから確定できません。", "游戏基础说明；导出数据中无法确定此品质的具体数值。"],
}


def main():
    root = Path(__file__).resolve().parents[1]
    module = ast.parse((root / "crimson_editor.py").read_text(encoding="utf-8-sig"))
    data = {}
    for name, lang in [("EN", "en"), ("PT", "pt")]:
        data[lang] = next(ast.literal_eval(node.value) for node in module.body
                          if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets))
    data["en"]["base_effect_note"] = "Game base text; the export does not resolve numbers for this quality."
    data["pt"]["base_effect_note"] = "Texto-base do jogo; o material exportado não resolve os números desta qualidade."
    for index, lang in enumerate(LANGS):
        data[lang] = {key: values[index] for key, values in ROWS.items()}
    for lang, values in data.items():
        missing = set(data["en"]) - set(values)
        if missing:
            raise ValueError(f"Missing {lang}: {sorted(missing)}")
    (root / "data/ui_translations.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(data)} complete interface languages, {len(data['en'])} keys each")


if __name__ == "__main__":
    main()
