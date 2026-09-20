"""Settings page -- thresholds, source enable/disable, processing rules
and retry controls, saved to config.yaml so they apply to the next run."""
import streamlit as st

from config import save_config


def render(db, cfg):
    st.title("⚙️ Settings")
    st.caption("Changes are saved to config.yaml and apply to the NEXT run/search-again — not retroactively.")

    st.markdown("#### Decision thresholds")
    c1, c2 = st.columns(2)
    auto_approve = c1.number_input("Auto-approval threshold", 0, 100, cfg["decision"]["auto_approve"])
    review_min = c2.number_input("Human-review minimum", 0, 100, cfg["decision"]["human_review_min"])

    st.markdown("#### Sources")
    all_sources = ["pexels", "unsplash", "pixabay", "foodish", "kaggle"]
    enabled = st.multiselect("Enabled sources", all_sources, default=cfg["search"]["sources"])
    max_retries = st.number_input("Maximum retries (Search Again)", 0, 10, cfg["search"]["max_retries"])

    st.markdown("#### Image spec")
    c1, c2, c3 = st.columns(3)
    width = c1.number_input("Width (px)", value=cfg["image"]["width"], step=50)
    height = c2.number_input("Height (px)", value=cfg["image"]["height"], step=50)
    max_mb = c3.number_input("Max file size (MB)", value=float(cfg["image"]["max_size_mb"]), step=0.5)

    st.markdown("#### Quality thresholds")
    c1, c2 = st.columns(2)
    blur_threshold = c1.number_input("Blur threshold (higher = stricter)", value=float(cfg["quality"]["blur_threshold"]))
    st.caption("Food subject coverage -- how much of the frame the dish should fill (measured with OpenCV GrabCut segmentation).")
    c3, c4, c5, c6 = st.columns(4)
    ideal_cov_min = c3.number_input("Ideal coverage min", 0.0, 1.0, float(cfg["quality"]["ideal_coverage_min"]), step=0.05)
    ideal_cov_max = c4.number_input("Ideal coverage max", 0.0, 1.0, float(cfg["quality"]["ideal_coverage_max"]), step=0.05)
    coverage_floor = c5.number_input("Coverage floor (hard fail below)", 0.0, 1.0, float(cfg["quality"]["coverage_floor"]), step=0.05)
    coverage_ceiling = c6.number_input("Coverage ceiling (hard fail above)", 0.0, 1.0, float(cfg["quality"]["coverage_ceiling"]), step=0.01)
    border_cutoff = c2.number_input("Border cut-off fail ratio (lower = stricter)",
                                    value=float(cfg["quality"]["border_cutoff_fail_ratio"]), step=0.05)

    st.markdown("#### AI vision (optional)")
    ai_enabled = st.checkbox("Enable AI vision scoring", value=cfg["ai"]["enabled"])
    ai_provider = st.radio("Primary provider", ["gemini", "groq"],
                           index=0 if cfg["ai"].get("provider", "gemini") == "gemini" else 1, horizontal=True)
    st.caption(
        "The other provider is used automatically as a fallback if the primary provider's call fails "
        "(bad key, timeout, rate limit) -- not for low scores, which are real results. "
        "Requires GEMINI_API_KEY and/or GROQ_API_KEY in your .env file; either one alone is enough to turn AI scoring on. "
        "If neither is available, its weight is redistributed onto the technical score."
    )

    st.markdown("#### Scoring weights (must sum to ~1.0)")
    c1, c2, c3, c4 = st.columns(4)
    ai_w = c1.number_input("AI weight", value=float(cfg["scoring"]["ai_weight"]), step=0.05)
    tech_w = c2.number_input("Technical weight", value=float(cfg["scoring"]["technical_weight"]), step=0.05)
    comp_w = c3.number_input("Composition weight", value=float(cfg["scoring"]["composition_weight"]), step=0.05)
    res_w = c4.number_input("Resolution weight", value=float(cfg["scoring"]["resolution_weight"]), step=0.05)
    total_w = round(ai_w + tech_w + comp_w + res_w, 2)
    st.caption(f"Current total: {total_w}" + ("" if abs(total_w - 1.0) < 0.01 else " ⚠️ doesn't sum to 1.0"))

    st.markdown("#### Storage")
    st.caption(
        "Approved images are uploaded straight to Drive and never kept locally. Rejected items are also "
        "uploaded to Drive (as an audit record) rather than just discarded -- either to a separate folder "
        "below, or into the same approved folder with a 'Rejected_' filename prefix if left blank."
    )
    destination = st.radio("Upload destination", ["google_drive", "local"],
                           index=0 if cfg["storage"]["destination"] == "google_drive" else 1, horizontal=True)
    drive_folder_id = st.text_input("Google Drive folder ID (approved images)",
                                    value=cfg["storage"].get("drive_folder_id", ""))
    rejected_drive_folder_id = st.text_input(
        "Google Drive folder ID for rejected items (optional -- leave blank to reuse the folder above)",
        value=cfg["storage"].get("rejected_drive_folder_id", ""),
    )

    st.markdown("#### Human Review")
    top_n = st.number_input(
        "Candidates shown per item in Human Review", 1, 6, int(cfg.get("review", {}).get("top_n", 3)),
        help="Only this many of the best-scoring candidates are kept as local image files and shown to a "
             "reviewer; the rest are scored and logged for audit, then their local copies deleted immediately.",
    )

    if st.button("💾 Save settings", type="primary"):
        new_cfg = dict(cfg)
        new_cfg["decision"] = {"auto_approve": auto_approve, "human_review_min": review_min}
        new_cfg["search"] = {**cfg["search"], "sources": enabled, "max_retries": max_retries}
        new_cfg["image"] = {"width": int(width), "height": int(height), "max_size_mb": max_mb}
        new_cfg["quality"] = {
            **cfg["quality"], "blur_threshold": blur_threshold,
            "ideal_coverage_min": ideal_cov_min, "ideal_coverage_max": ideal_cov_max,
            "coverage_floor": coverage_floor, "coverage_ceiling": coverage_ceiling,
            "border_cutoff_fail_ratio": border_cutoff,
        }
        new_cfg["ai"] = {**cfg["ai"], "enabled": ai_enabled, "provider": ai_provider}
        new_cfg["scoring"] = {"ai_weight": ai_w, "technical_weight": tech_w,
                              "composition_weight": comp_w, "resolution_weight": res_w}
        new_cfg["storage"] = {
            "destination": destination, "drive_folder_id": drive_folder_id,
            "rejected_drive_folder_id": rejected_drive_folder_id,
        }
        new_cfg["review"] = {**cfg.get("review", {}), "top_n": int(top_n)}
        save_config(new_cfg)
        st.success("Settings saved to config.yaml.")
        st.rerun()
