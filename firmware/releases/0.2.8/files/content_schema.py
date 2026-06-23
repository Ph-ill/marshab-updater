# Authoritative content surface for the incremental MarsHab game.
# Engine code references these tables; content_manifest.json is generated from them.
POOLS=('weather','colony_life','equipment','anomaly','discovery')
ACTIONS=('vent_co2','reroute_power','collect_ice','sift_regolith','grow_rations','decode_signal','run_atmo_processor','survey_crater','print_spares','seed_bioreactor','stabilize_dome','open_airlock')
ACTION_META={
 'vent_co2':('Vent CO2','Core life-support action; scrubbers cough awake.',1),
 'reroute_power':('Reroute Power','Balance batteries and sun-starved circuits.',1),
 'collect_ice':('Collect Ice','Send drones to scrape usable ice from shaded cuts.',1),
 'sift_regolith':('Sift Regolith','Sort dust and rock for useful feedstock.',1),
 'grow_rations':('Grow Rations','Coax calories from the first greenhouse trays.',2),
 'decode_signal':('Decode Signal','Spend power on the recurring buried transmission.',3),
 'run_atmo_processor':('Pulse Atmo Processor','Fire a slow terraforming processor cycle.',4),
 'survey_crater':('Survey Crater','Map an old impact scar beyond the beacons.',2),
 'print_spares':('Print Spares','Fabricate emergency parts from stored feedstock.',3),
 'seed_bioreactor':('Seed Bioreactor','Wake the sealed microbe vats.',4),
 'stabilize_dome':('Stabilize Dome','Tune pressure and thermal flex in the outer dome.',3),
 'open_airlock':('Open Airlock','Prepare the final controlled exposure sequence.',5)
}
EVENT_TOPICS={
 'weather':['dust_storm_minor','static_sky','red_horizon','ice_fog','pressure_twitch','solar_glare','night_freeze','grit_on_panels','thin_cloud','charged_dust','storm_wall','clear_cold','low_sun','eclipse_dim','frost_ring','haze_bloom'],
 'colony_life':['sleep_shift','ration_vote','hydroponic_laugh','child_question','repair_song','greenhouse_queue','crew_argument','quiet_meal','work_roster','birthday_ping','dome_walk','new_nickname','shared_coffee','bunk_light','exercise_loop','first_sprout'],
 'equipment':['pump_cough','battery_warm','valve_resonance','filter_warning','drone_return','printer_jam','antenna_slew','seal_check','heater_cycle','sensor_noise','compressor_tick','backup_boot','servo_stutter','cable_frost','scrubber_grit','relay_chatter'],
 'anomaly':['subsurface_ping','impossible_echo','archive_checksum','warm_stone','ghost_packet','pattern_in_dust','old_beacon','wrong_shadow','buried_heat','silent_reply','spectral_line','memory_leak','clock_skip','map_gap','coded_lullaby','redacted_star'],
 'discovery':['ore_thread','ice_lens','microbe_trace','glass_tube','buried_panel','fossil_ripple','lost_rover','pressure_cave','salt_marker','seed_cache','old_bootprint','basalt_door','clear_sample','warm_vent','sky_reading','soil_bloom']
}
AWAY_TOPICS=['power_hum','dust_on_panels','greenhouse_grew','cold_shift','crew_rested','stores_shifted','drones_returned','signal_repeated','filters_loaded','ice_melted','pressure_held','weather_passed','printer_finished','archive_indexed','microbes_woke','storm_scrubbed','children_named_stars','battery_bank_filled','ration_batch_set','dome_seals_sang','strange_ping_waited','new_path_mapped','frost_receded','hab_smelt_of_iron','old_log_resurfaced','colonists_left_notes','panels_cleared','water_tanks_settled','soil_warmed','antenna_tracked']
ARCHIVE_STRANDS={
 'precursor':12,
 'colony_journal':10,
 'system_memory':10,
 'terraforming':8,
 'signal':8
}
BEAT_IDS=['beat_act1_open','beat_act2_open','beat_act3_open','beat_act4_open','beat_act5_open','beat_first_solar_array','beat_first_ice_well','beat_first_greenhouse','beat_population_8','beat_population_12','beat_first_fab_shop','beat_first_trade','beat_first_decode','beat_decode_3','beat_first_crater_survey','beat_first_dome_stable','beat_first_atmo_processor','beat_atmosphere_025','beat_atmosphere_050','beat_first_bioreactor','beat_temperature_rise','beat_biomass_trace','beat_first_open_air_test','beat_final_threshold','beat_archive_precursor_complete','beat_signal_understood','beat_colony_self_sufficient','beat_children_under_sky','beat_last_storm','beat_act5_choice']
SENDERS=('botanist','engineer','doctor','quartermaster','child','director','unknown','cartographer')
UI_AREAS={
 'tab':['hab','surface','colony','trade','archive','terraform','ending'],
 'resource':['o2','power','water','food','regolith','population','ice','rare_metals','polymer','alloy','atmosphere','temperature','biomass'],
 'button':['sync','build','trade','tend','archive','letters','ending','dismiss','settings','save_wifi','reconnect','install','provision','copy_code','redeem_code'],
 'header':['hab_status','actions','modules','events','away','archive','letters','ending','resources','population','wifi','firmware'],
 'tip':['cooldown','insufficient','locked','offline','power_cycle','gateway','passport','archive_unlock','no_repeat','catchup','protected_save','content_stub','act_gate','ending_locked']
}
ENDING=[
 'signal_decoded','door_beneath_basalts','old_intelligence','terraforming_choice','first_breath','storm_breaks','children_outside','machine_confession','precursor_answer','green_horizon','colony_reply','epilogue_seed']

def act_range_for_pool(pool, idx):
    if pool in ('weather','equipment'): return '1-5'
    if pool=='colony_life': return '2-5' if idx>3 else '1-5'
    if pool=='anomaly': return '2-5' if idx<6 else '3-5'
    return '2-5' if idx<5 else '3-5'

def event_entries():
    out=[]
    for pool in POOLS:
        for i,name in enumerate(EVENT_TOPICS[pool]):
            out.append({'id':'evt_%s_%s'%(pool,name),'type':'events','pool':pool,'act':act_range_for_pool(pool,i),'weight':8 if i<4 else (5 if i<10 else 3),'context':'Ambient %s event: %s. Not an action result; can appear live or in away digest.'%(pool,name.replace('_',' ')),'max_chars':140,'trigger_summary':'weighted random pool draw; act %s'%act_range_for_pool(pool,i)})
    return out

def action_entries():
    out=[]
    for aid in ACTIONS:
        label,flavor,act=ACTION_META[aid]
        out.append({'id':'act_'+aid,'type':'actions','act':act,'context':'Action entry. label=%s; flavor=%s; result_1..4 are varied immediate success lines.'%(label,flavor),'max_chars':110,'trigger_summary':'action unlocked act>=%s'%act,'fields':['label','flavor','result_1','result_2','result_3','result_4']})
    return out

def away_entries():
    out=[]
    for i,name in enumerate(AWAY_TOPICS):
        pool='systems' if i<10 else ('colony' if i<20 else 'mystery')
        act='1-5' if i<10 else ('2-5' if i<22 else '3-5')
        out.append({'id':'away_'+name,'type':'away','pool':pool,'act':act,'context':'Composable while-away digest fragment; gated by elapsed resources/events/act: %s.'%name.replace('_',' '),'max_chars':130,'trigger_summary':'catch-up digest fragment; %s'%act})
    return out

def archive_entries():
    out=[]
    for strand,count in ARCHIVE_STRANDS.items():
        for n in range(1,count+1):
            act=1 if strand=='system_memory' and n<=2 else (2 if n<=3 else (3 if n<=7 else (4 if n<=10 else 5)))
            cond='act>=%d && %s_count>=%d'%(act,strand,n-1)
            out.append({'id':'arc_%s_%02d'%(strand,n),'type':'archive','strand':strand,'seq':n,'act':act,'unlock_after':cond,'context':'Archive strand %s entry %02d. Progressive mystery/lore chain; sequence must read in order.'%(strand,n),'max_chars':900,'trigger_summary':'archive unlock chain'})
    return out

def beat_entries():
    out=[]
    for i,bid in enumerate(BEAT_IDS):
        act=1 if i<7 else (2 if i<14 else (3 if i<20 else (4 if i<25 else 5)))
        out.append({'id':bid,'type':'beats','act':act,'seq':i+1,'unlock_after':'milestone:%s'%bid.replace('beat_',''),'context':'Milestone/transition beat for %s. Short punchy story beat, not ambient log noise.'%bid.replace('_',' '),'max_chars':520,'trigger_summary':'internal milestone or act transition'})
    return out

def letter_entries():
    out=[]; seq=1
    for sender in SENDERS:
        for n in range(1,5):
            act=1 if n==1 and sender in ('botanist','engineer') else min(5,n+1)
            out.append({'id':'ltr_%s_%02d'%(sender,n),'type':'letters','sender':sender,'seq':n,'act':act,'unlock_after':'act>=%d && letter_seq_%s>=%d'%(act,sender,n-1),'context':'Recurring sender %s letter %02d. Establish distinct voice and evolving relationship.'%(sender,n),'max_chars':750,'trigger_summary':'letter unlock across arc'})
            seq+=1
    return out

def ui_entries():
    out=[]
    for area,names in UI_AREAS.items():
        for name in names:
            out.append({'id':'ui_%s_%s'%(area,name),'type':'ui','context':'UI copy for %s %s.'%(area,name.replace('_',' ')),'max_chars':60,'trigger_summary':'interface label/help text'})
    return out

def ending_entries():
    return [{'id':'end_%02d_%s'%(i+1,name),'type':'ending','seq':i+1,'act':5,'unlock_after':'ending_seq==%d'%i,'context':'Ordered ending payoff fragment %02d: %s. High craft; reveal/climax/epilogue sequence.'%(i+1,name.replace('_',' ')),'max_chars':700,'trigger_summary':'ordered ending sequence'} for i,name in enumerate(ENDING)]

def all_entries():
    out=[]
    for fn in (event_entries,action_entries,away_entries,archive_entries,beat_entries,letter_entries,ui_entries,ending_entries): out += fn()
    return out

def ids_by_type(t): return [e['id'] for e in all_entries() if e['type']==t]
def event_pool_ids(pool, act):
    ids=[]
    for e in event_entries():
        if e['pool']!=pool: continue
        a=str(e['act'])
        lo=int(a.split('-')[0]); hi=int(a.split('-')[-1])
        if lo<=act<=hi: ids.append((e['id'],e['weight']))
    return ids
