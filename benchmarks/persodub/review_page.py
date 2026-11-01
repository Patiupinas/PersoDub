"""Offline human-rating interface for the existing blinded A/B pack.

Only neutral A/B labels and preselected source clips are exposed. The solution
mapping stays in the private key file outside the reviewer directory.
"""
from __future__ import annotations

from html import escape

RATING_COLUMNS = [
    "rater_id", "native_ru_self_reported", "pair_id", "A_file", "B_file", "source_file",
    "target_text", "A_accent_1to5", "B_accent_1to5",
    "A_voice_1to5", "B_voice_1to5", "A_pauses_1to5",
    "B_pauses_1to5", "A_original_audibility_1to5",
    "B_original_audibility_1to5", "preference_A_B_tie", "notes",
]

METRICS = [
    ("accent_1to5", "Естественность русского произношения"),
    ("voice_1to5", "Сходство голоса с оригиналом"),
    ("pauses_1to5", "Естественность ритма и пауз"),
    ("original_audibility_1to5", "Слышимость исходного голоса"),
]


def _rating_select(name):
    # No score is preselected: blank answers cannot silently become a MOS 3.
    options = '<option value="">Не выбрано</option>' + "".join(
        f'<option value="{n}">{n}</option>' for n in range(1, 6)
    )
    return f'<select name="{name}" required aria-label="{name}">{options}</select>'


def make_page(cases, voice_only=False):
    """Render a local HTML page from already validated case IDs.

    Each item is (id, has_source_reference, Russian target). No audio paths
    or provider assignments may be added by callers to this renderer.
    """
    cards = []
    for case_id, source_present, target in cases:
        case = escape(case_id, quote=True)
        target_html = escape(target, quote=True)
        if source_present:
            original = (f'<label>Оригинальный голос'
                        f'<audio controls preload="none" src="{case}/source.wav"></audio>'
                        f'</label>')
        else:
            original = "<p>Оригинальный образец отсутствует</p>"
        rows = "".join(
            f'<tr><th scope="row">{escape(title)}</th>'
            f'<td>{_rating_select("A_" + suffix)}</td>'
            f'<td>{_rating_select("B_" + suffix)}</td></tr>'
            for suffix, title in METRICS
            if not voice_only or suffix != "original_audibility_1to5"
        )
        cards.append(
            f'<section class="pair" data-id="{case}" data-source="{int(source_present)}">'
            f'<h2>Запись {case}</h2>'
            f'<p class="script">{target_html}</p>'
            f'<div class="players">{original}'
            f'<label>Вариант A<audio controls preload="none" src="{case}/A.wav"></audio></label>'
            f'<label>Вариант B<audio controls preload="none" src="{case}/B.wav"></audio></label>'
            f'</div>'
            f'<table><thead><tr><th>Критерий</th><th>A</th><th>B</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
            f'<label>Предпочтение'
            f'<select name="preference_A_B_tie" required>'
            f'<option value="">Не выбрано</option>'
            f'<option value="A">A</option><option value="B">B</option>'
            f'<option value="tie">Одинаково</option></select></label>'
            f'<label>Замечания<textarea name="notes" rows="2"'
            f' placeholder="Произношение, интонация, тембр, паузы..."></textarea></label>'
            f'</section>'
        )
    import json
    columns = json.dumps(RATING_COLUMNS)
    profile_note = (
        "Это голосовые записи без оригинальной подложки: слышимость оригинала N/A."
        if voice_only else
        "Оцените слышимость исходного голоса под новой дорожкой."
    )
    # No remote requests, remote resources, or hidden provider metadata.
    template = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PersoDub - слепое сравнение озвучки</title>
<style>
:root{font-family:system-ui,sans-serif;color:#17212a;background:#f5f7fa}
*{box-sizing:border-box}body{max-width:940px;margin:0 auto;padding:20px}
h1{font-size:1.55rem}h2{font-size:1.15rem}p{line-height:1.55}
.pair{background:#fff;margin:18px 0;border:1px solid #dce2e9;border-radius:12px;padding:20px}
.script{padding:10px;background:#f3f6f8;border-radius:6px;white-space:pre-wrap}
.players{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.players label{padding:10px;border-radius:6px;background:#eff3f6;font-weight:600}
audio{display:block;width:100%;margin-top:9px}
table{width:100%;border-collapse:collapse;margin:16px 0}
th,td{text-align:left;padding:9px;border-bottom:1px solid #e4eaf0}
select,input,textarea{font:inherit;padding:8px;max-width:100%;border:1px solid #aab8c5;border-radius:6px}
td select{width:100%}.pair>label{display:block;margin:14px 0}
.pair>label select,.pair>label textarea{display:block;width:100%;margin:7px 0}
.controls{background:#fff;border:1px solid #dce2e9;border-radius:10px;padding:16px}
.native{display:block;margin:12px 0}.native input{width:auto}
button{background:#165ba5;color:white;border:0;border-radius:7px;padding:12px 20px;font:inherit;cursor:pointer}
button:hover{background:#124a86}#message{min-height:1.5em;margin-top:10px}
@media(max-width:540px){body{padding:12px}.pair{padding:12px}th,td{padding:5px}}
</style></head><body>
<h1>PersoDub - независимая оценка</h1>
<p>Слушайте A и B, при наличии сравнивайте с оригиналом. Шкала: 1 - плохо, 5 - отлично.
Порядок A/B скрывает модель и параметры голоса. Оценки не отправляются на сервер.</p>
<p>__PROFILE_NOTE__</p>
<div class="controls"><label>Код рецензента
<input id="rater" required maxlength="50" placeholder="Например: reviewer-01"></label>
<label class="native"><input id="native-ru" type="checkbox"> Русский язык - родной (самооценка)</label>
<button type="button" id="export">Скачать заполненный CSV</button>
<div id="message" role="status" aria-live="polite"></div></div>
__CARDS__
<script>
'use strict';
const columns=__COLUMNS__;
const voiceOnly=__VOICE_ONLY__;
const pairs=[...document.querySelectorAll('.pair')];
function spreadsheetCell(value){
  let str=String(value??'');
  // Escape values that spreadsheets could interpret as formulas.
  if(/^[=+@\\-]/.test(str))str="'"+str;
  return '"'+str.replace(/"/g,'""')+'"';
}
function downloadRatings(){
  const rater=document.getElementById('rater');
  const message=document.getElementById('message');
  message.textContent='';
  if(!rater.value.trim()){rater.focus();message.textContent='Введите код рецензента.';return;}
  const entries=[];
  for(const pair of pairs){
    const missing=[...pair.querySelectorAll('select[required]')].find(el=>!el.value);
    if(missing){missing.focus();message.textContent='Оцените все параметры записи '+pair.dataset.id+'.';return;}
    const values={
      rater_id:rater.value.trim(),
      native_ru_self_reported:document.getElementById('native-ru').checked?'yes':'no',
      pair_id:pair.dataset.id,
      A_file:pair.dataset.id+'/A.wav',B_file:pair.dataset.id+'/B.wav',
      source_file:pair.dataset.source==='1'?pair.dataset.id+'/source.wav':'',
      target_text:pair.querySelector('.script').textContent,
    };
    for(const control of pair.querySelectorAll('select,textarea')){
      values[control.name]=control.value;
    }
    if(voiceOnly){
      values.A_original_audibility_1to5='N/A';
      values.B_original_audibility_1to5='N/A';
    }
    entries.push(values);
  }
  const lines=[columns.map(spreadsheetCell).join(','),
    ...entries.map(entry=>columns.map(col=>spreadsheetCell(entry[col]??'')).join(','))];
  const url=URL.createObjectURL(new Blob(['\\ufeff'+lines.join('\\r\\n')+'\\r\\n'],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;
  a.download='persodub-ratings-'+rater.value.trim().replace(/[^a-z0-9_-]/gi,'_')+'.csv';
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),2000);
  message.textContent='CSV сформирован локально. Передайте файл для анализа.';
}
document.getElementById('export').addEventListener('click',downloadRatings);
</script></body></html>"""
    return (template.replace("__CARDS__", "\n".join(cards))
            .replace("__COLUMNS__", columns)
            .replace("__VOICE_ONLY__", json.dumps(bool(voice_only)))
            .replace("__PROFILE_NOTE__", escape(profile_note)))
