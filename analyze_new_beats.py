import subprocess, struct, math, os, re

USED = {"5_in_da_marnin","adx","all_alone","army","b3lt_144","bappin","beatspink_pussy","black_fade_126","blockz","bnb","boppy","carl_malone","changed_on_me","cloudz_144","dawg_shit","drake","ever_since_i_met_you_leek_x_fritokeyz","fast_car","game_time","go_dj_chi","going_down_168","guard_up_139","h33d_145","hood_legend","kethup_155","king_fy3","lady_shot_caller","ltf_x_tommy_trax","ltf_x_tommy_trax_3","magic_155","massacre_147","master_plan","meineliebe","mighty_morphin","mormon_152","ohare_2","paul_walker","pop","provide","punction","r3d_truk__2","she_will","soft_162_fyso","st3r_145","time","trinket","uav","weapons_150","ye"}

def safe_stem(fn):
    s = os.path.splitext(os.path.basename(fn))[0].lower().strip()
    s = re.sub(r"[^\w\s-]","",s); s = re.sub(r"\s+","_",s); s = re.sub(r"_+","_",s)
    return s.strip("_")
