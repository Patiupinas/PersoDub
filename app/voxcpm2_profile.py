"""Pinned, research-reviewed model identity for optional Russian VoxCPM2 speech."""
MODEL_ID = "openbmb/VoxCPM2"
MODEL_REVISION = "32279effe8c19989596f05d353d1447f51d9e915"
VOXCPM2_RU_VOICES = ("kseniya", "aidar")
VOXCPM2_PROFILE = "p1-ru-vocal-20261105"
STYLE_PREFIX = (
    "(A native Russian vocal teacher, warm, clear articulation, "
    "lively natural speech with thoughtful pauses) "
)
# The owner selected the actual P1 2026-11-06 cloned-reference expression trial.
# Keep its exact text prefix and inference parameters, independent of the
# existing fixed-Russian preset profile.
VOXCPM2_EXPRESSIVE_PROFILE = "p1-source-voice-expressive-20261106"
VOXCPM2_EXPRESSIVE_PREFIX = "(воодушевлённо, с энергичной поддерживающей интонацией)"
