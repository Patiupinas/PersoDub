"""Full-source speech coverage is separate from preserving source-only exercises."""
import pytest

from app.audio.overdub import OverdubError, select_translatable_cues, source_speech_coverage

RATE=48000


def _cues():
    return [
        {"start": 0.0, "end": 2.0, "text": "one"},
        {"start": 3.0, "end": 5.0, "text": "two"},
        {"start": 7.0, "end": 9.0, "text": "three"},
    ]


def _span(a,b,action):
    return type("S", (), {"start":int(a*RATE),"end":int(b*RATE),"action":action})()


def test_complete_all_spoken_cues_but_gaps_remain_at_original_volume():
    cues=_cues()
    selected,skipped=select_translatable_cues(cues,[
        _span(0,2,"TRANSLATE"),_span(2,3,"REVIEW"),
        _span(3,5,"TRANSLATE"),_span(5,7,"PRESERVE"),
        _span(7,9,"TRANSLATE"),_span(9,10,"REVIEW"),
    ])
    assert skipped==0
    result=source_speech_coverage(cues,selected,10*RATE)
    assert result["status"]=="ALL_TRANSCRIBED_SPEECH_CUES_SELECTED"
    assert result["source_cues"]==3
    assert result["translated_cues"]==3
    assert result["source_only_cues"]==0
    assert result["source_cue_coverage_percent"]==100.0
    assert result["source_speech_time_coverage_percent"]==100.0
    assert result["source_speech_seconds"]==6.0
    assert result["translated_source_cue_seconds"]==6.0
    assert result["outside_source_cue_seconds"]==4.0
    assert result["human_verified_exercises"] is False


def test_partial_translation_flags_missing_speech_even_if_video_exports():
    cues=_cues()
    selected, skipped=select_translatable_cues(cues,[
        _span(0,2,"TRANSLATE"),_span(2,3,"REVIEW"),
        _span(3,10,"PRESERVE"),
    ])
    assert skipped==2
    result=source_speech_coverage(cues,selected,10*RATE)
    assert result["status"]=="INCOMPLETE_SOURCE_SPEECH_COVERAGE"
    assert result["translated_cues"]==1
    assert result["source_only_cues"]==2
    assert result["source_cue_coverage_percent"]==pytest.approx(33.333333,abs=.0001)
    assert result["source_speech_time_coverage_percent"]==pytest.approx(33.333333,abs=.0001)
    assert result["uncovered_source_cue_numbers"]==[2,3]
    assert result["outside_source_cue_seconds"]==4.0


def test_overlapping_cues_count_time_once():
    cues=[
        {"start": 0,"end": 3,"text":"A"},
        {"start": 2,"end": 5,"text":"B"},
    ]
    selected=[{**cues[0],"source_cue_number":1,"dub_limit_s":3}]
    result=source_speech_coverage(cues,selected,6*RATE)
    assert result["source_speech_seconds"]==5
    assert result["translated_source_cue_seconds"]==3
    assert result["source_speech_time_coverage_percent"]==60
    assert result["outside_source_cue_seconds"]==1


def test_stale_or_duplicate_synthesis_reference_cannot_be_marked_complete():
    cues=_cues()
    with pytest.raises(OverdubError,match="source"):
        source_speech_coverage(cues,[{**cues[0],"source_cue_number":3}],10*RATE)
    selected=[{**cues[0],"source_cue_number":1}]
    with pytest.raises(OverdubError,match="duplicate"):
        source_speech_coverage(cues,selected+selected,10*RATE)


def test_original_only_audio_with_no_speech_is_not_misclassified_as_missing_translation():
    result=source_speech_coverage([],[],48000)
    assert result["status"]=="NO_TRANSCRIBED_SPEECH"
    assert result["outside_source_cue_seconds"]==1.0
    assert result["source_cue_coverage_percent"] is None


def test_short_source_can_not_claim_speech_beyond_source_clock():
    with pytest.raises(OverdubError,match="source"):
        source_speech_coverage(
            [{"start":0,"end":5,"text":"outside"}],[],4*RATE
        )
