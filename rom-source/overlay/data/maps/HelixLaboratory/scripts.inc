HelixLaboratory_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, HelixGenesisLab_OnTransition
	map_script MAP_SCRIPT_ON_FRAME_TABLE, HelixGenesisLab_OnFrame
	.byte 0
HelixGenesisLab_OnTransition:
	special GetHelixGenesisState
	setvar VAR_TEMP_1, 0
	end
HelixGenesisLab_OnFrame:
	map_script_2 VAR_TEMP_0, 1, HelixGenesisLab_Welcome
	.2byte 0
HelixGenesisLab_Welcome:
	lockall
	setvar VAR_TEMP_0, 0
	special MarkHelixGenesisWelcome
	msgbox HelixGenesisLab_Text_Welcome, MSGBOX_DEFAULT
	releaseall
	end
HelixGenesisLab_Exit::
	lockall
	special GetHelixGenesisState
	goto_if_ge VAR_RESULT, 6, HelixGenesisLab_Leave
	msgbox HelixGenesisLab_Text_Stay, MSGBOX_DEFAULT
	applymovement LOCALID_PLAYER, HelixGenesisLab_StepBack
	waitmovement 0
	releaseall
	end
HelixGenesisLab_Leave:
	warp MAP_OLDALE_TOWN_HOUSE1, 4, 6
	waitstate
	releaseall
	end
HelixGenesisLab_StepBack:
	walk_up
	step_end

HelixGenesisLab_Reception::
	lock
	faceplayer
	msgbox HelixGenesisLab_Text_Reception, MSGBOX_DEFAULT
	closemessage
	multichoice 9, 0, MULTI_HELIX_RECEPTION, FALSE
	switch VAR_RESULT
	case 0, HelixGenesisLab_RegistrationLocked
	case 1, HelixGenesisLab_ChatReception
	case 2, HelixGenesisLab_Progress
	goto HelixGenesisLab_Finish
HelixGenesisLab_Registration::
	lockall
HelixGenesisLab_RegistrationLocked:
	msgbox HelixGenesisLab_Text_Soul, MSGBOX_DEFAULT
	closemessage
	multichoice 10, 0, MULTI_HELIX_SOUL, FALSE
	goto_if_ge VAR_RESULT, 3, HelixGenesisLab_Finish
	copyvar VAR_0x8004, VAR_RESULT
	addvar VAR_0x8004, 1
	special SetHelixGenesisSoul
	msgbox HelixGenesisLab_Text_Dna, MSGBOX_DEFAULT
	closemessage
	multichoice 8, 0, MULTI_HELIX_DNA, FALSE
	goto_if_ge VAR_RESULT, 2, HelixGenesisLab_Registered
	copyvar VAR_0x8004, VAR_RESULT
	special SetHelixGenesisDnaTutorial
	goto_if_eq VAR_0x8004, 0, HelixGenesisLab_Registered
	msgbox HelixGenesisLab_Text_Synthetic, MSGBOX_DEFAULT
HelixGenesisLab_Registered:
	msgbox HelixGenesisLab_Text_Registered, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish

HelixGenesisLab_Geneticist::
	lock
	faceplayer
	msgbox HelixGenesisLab_Text_Geneticist, MSGBOX_DEFAULT
	closemessage
	multichoice 8, 0, MULTI_HELIX_GENETICIST, FALSE
	switch VAR_RESULT
	case 0, HelixGenesisLab_AnalysisLocked
	case 1, HelixGenesisLab_GeneticsDepth
	case 2, HelixGenesisLab_ChatGeneticist
	goto HelixGenesisLab_Finish
HelixGenesisLab_Analysis::
	lockall
HelixGenesisLab_AnalysisLocked:
	special GetHelixGenesisState
	goto_if_lt VAR_RESULT, 2, HelixGenesisLab_NeedRegister
	goto_if_ge VAR_RESULT, 4, HelixGenesisLab_LockedRecipe
	msgbox HelixGenesisLab_Text_Analysis, MSGBOX_DEFAULT
	closemessage
	multichoice 7, 0, MULTI_HELIX_RECIPES, FALSE
	goto_if_ge VAR_RESULT, 2, HelixGenesisLab_Finish
	copyvar VAR_0x8004, VAR_RESULT
	addvar VAR_0x8004, 1
	goto_if_eq VAR_0x8004, 2, HelixGenesisLab_SecondRecipe
	msgbox HelixGenesisLab_Text_RecipeOne, MSGBOX_DEFAULT
	showmonpic SPECIES_HELIX_FOUNDER_ONE, 10, 3
	goto HelixGenesisLab_ConfirmRecipe
HelixGenesisLab_SecondRecipe:
	msgbox HelixGenesisLab_Text_RecipeTwo, MSGBOX_DEFAULT
	showmonpic SPECIES_HELIX_FOUNDER_TWO, 10, 3
HelixGenesisLab_ConfirmRecipe:
	msgbox HelixGenesisLab_Text_ConfirmRecipe, MSGBOX_YESNO
	hidemonpic
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_Cancel
	special SelectHelixGenesisRecipe
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_Invalid
	msgbox HelixGenesisLab_Text_RecipeSelected, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_GeneticsDepth:
	msgbox HelixGenesisLab_Text_Depth, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_LockedRecipe:
	special BufferHelixGenesis
	msgbox HelixGenesisLab_Text_LockedRecipe, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish

HelixGenesisLab_Preparation::
	lockall
	special GetHelixGenesisState
	goto_if_lt VAR_RESULT, 3, HelixGenesisLab_NeedRecipe
	goto_if_ge VAR_RESULT, 4, HelixGenesisLab_AlreadyPrepared
	special BufferHelixGenesis
	msgbox HelixGenesisLab_Text_Prepare, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_Cancel
	special PrepareHelixGenesis
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_Invalid
	fadescreen FADE_TO_BLACK
	delay 24
	fadescreen FADE_FROM_BLACK
	msgbox HelixGenesisLab_Text_Prepared, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_AlreadyPrepared:
	msgbox HelixGenesisLab_Text_AlreadyPrepared, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish

HelixGenesisLab_Nursery::
	lock
	faceplayer
	msgbox HelixGenesisLab_Text_Nursery, MSGBOX_DEFAULT
	closemessage
	multichoice 9, 0, MULTI_HELIX_NURSERY, FALSE
	switch VAR_RESULT
	case 0, HelixGenesisLab_IncubatorLocked
	case 1, HelixGenesisLab_FollowupLocked
	case 2, HelixGenesisLab_ChatNursery
	goto HelixGenesisLab_Finish
HelixGenesisLab_Incubator::
	lockall
HelixGenesisLab_IncubatorLocked:
	special GetHelixGenesisState
	goto_if_lt VAR_RESULT, 4, HelixGenesisLab_NeedPreparation
	goto_if_ge VAR_RESULT, 6, HelixGenesisLab_Cross
	goto_if_eq VAR_RESULT, 5, HelixGenesisLab_HatchOffer
	msgbox HelixGenesisLab_Text_Incubate, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_Cancel
	special IncubateHelixGenesis
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_Invalid
	fadescreen FADE_TO_BLACK
	delay 60
	fadescreen FADE_FROM_BLACK
	msgbox HelixGenesisLab_Text_Incubated, MSGBOX_DEFAULT
HelixGenesisLab_HatchOffer:
	special BufferHelixGenesis
	msgbox HelixGenesisLab_Text_Hatch, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_Cancel
	special AdmitHelixGenesis
	goto_if_eq VAR_RESULT, 7, HelixGenesisLab_Full
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_Invalid
	playfanfare MUS_OBTAIN_ITEM
	msgbox HelixGenesisLab_Text_Born, MSGBOX_DEFAULT
	waitfanfare
	special GetHelixGenesisState
	goto_if_eq VAR_0x8005, 1, HelixGenesisLab_BondCurious
	goto_if_eq VAR_0x8005, 2, HelixGenesisLab_BondCare
	msgbox HelixGenesisLab_Text_BondPatient, MSGBOX_DEFAULT
	goto HelixGenesisLab_AfterBirth
HelixGenesisLab_BondCurious:
	msgbox HelixGenesisLab_Text_BondCurious, MSGBOX_DEFAULT
	goto HelixGenesisLab_AfterBirth
HelixGenesisLab_BondCare:
	msgbox HelixGenesisLab_Text_BondCare, MSGBOX_DEFAULT
HelixGenesisLab_AfterBirth:
	giveitem ITEM_POKE_BALL, 5
	msgbox HelixGenesisLab_Text_Next, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_AlreadyBorn:
	msgbox HelixGenesisLab_Text_AlreadyBorn, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish

HelixGenesisLab_Followup::
	lockall
HelixGenesisLab_FollowupLocked:
	closemessage
	special GetHelixLabLanguage
	goto_if_eq VAR_RESULT, 1, HelixGenesisLab_NotesPT
	multichoice 1, 0, MULTI_HELIX_NOTES_EN, FALSE
	goto HelixGenesisLab_NotesChoice
HelixGenesisLab_NotesPT:
	multichoice 1, 0, MULTI_HELIX_NOTES_PT, FALSE
HelixGenesisLab_NotesChoice:
	goto_if_ge VAR_RESULT, 5, HelixGenesisLab_Finish
	copyvar VAR_0x8004, VAR_RESULT
	special BufferHelixLabPage
	goto_if_ne VAR_0x8004, 4, HelixGenesisLab_NotesPage
	goto_if_lt VAR_RESULT, 2, HelixGenesisLab_NotesPage
	goto_if_gt VAR_RESULT, 3, HelixGenesisLab_NotesPage
	msgbox gStringVar4, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_FollowupLocked
	special HealPlayerParty
	setvar VAR_0x8004, 5
	special BufferHelixLabPage
HelixGenesisLab_NotesPage:
	goto_if_eq VAR_0x8009, 0, HelixGenesisLab_NotesText
	showmonpic VAR_0x8009, 10, 3
	msgbox gStringVar4, MSGBOX_DEFAULT
	hidemonpic
	goto HelixGenesisLab_FollowupLocked
HelixGenesisLab_NotesText:
	msgbox gStringVar4, MSGBOX_DEFAULT
	goto HelixGenesisLab_FollowupLocked

HelixGenesisLab_Rival::
	lock
	faceplayer
	special GetHelixGenesisState
	goto_if_lt VAR_RESULT, 6, HelixGenesisLab_RivalWait
	goto_if_eq VAR_0x8007, 1, HelixGenesisLab_RivalDone
	msgbox HelixGenesisLab_Text_Rival, MSGBOX_YESNO
	goto_if_eq VAR_RESULT, NO, HelixGenesisLab_Finish
	special PrepareHelixRival
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_RivalHeal
	cleartrainerflag TRAINER_HELIX_NOA
	trainerbattle_earlyrival TRAINER_HELIX_NOA, RIVAL_BATTLE_HEAL_AFTER, HelixGenesisLab_Text_RivalDefeat, HelixGenesisLab_Text_RivalVictory
	special FinishHelixRival
	special HealPlayerParty
	msgbox HelixGenesisLab_Text_RivalAfter, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_RivalWait:
	msgbox HelixGenesisLab_Text_RivalWait, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_RivalDone:
	msgbox HelixGenesisLab_Text_RivalDone, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_RivalHeal:
	msgbox HelixGenesisLab_Text_RivalHeal, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish

HelixGenesisLab_ChatReception:
	setvar VAR_0x8004, 2
	goto HelixGenesisLab_Chat
HelixGenesisLab_ChatGeneticist:
	setvar VAR_0x8004, 3
	goto HelixGenesisLab_Chat
HelixGenesisLab_ChatNursery:
	setvar VAR_0x8004, 4
HelixGenesisLab_Chat:
	special RequestLabDialogue
	waitstate
	msgbox gStringVar4, MSGBOX_DEFAULT
	special EndAiDialogue
	goto HelixGenesisLab_Finish
HelixGenesisLab_Progress:
	special GetHelixGenesisState
	goto_if_lt VAR_RESULT, 2, HelixGenesisLab_NeedRegister
	goto_if_lt VAR_RESULT, 3, HelixGenesisLab_NeedRecipe
	goto_if_lt VAR_RESULT, 4, HelixGenesisLab_NeedPreparation
	goto_if_lt VAR_RESULT, 6, HelixGenesisLab_NeedIncubator
	msgbox HelixGenesisLab_Text_Next, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_NeedRegister:
	msgbox HelixGenesisLab_Text_NeedRegister, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_NeedRecipe:
	msgbox HelixGenesisLab_Text_NeedRecipe, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_NeedPreparation:
	msgbox HelixGenesisLab_Text_NeedPreparation, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_NeedIncubator:
	msgbox HelixGenesisLab_Text_NeedIncubator, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_Cancel:
	msgbox HelixGenesisLab_Text_Cancel, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_Full:
	msgbox HelixGenesisLab_Text_Full, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_Invalid:
	msgbox HelixGenesisLab_Text_Invalid, MSGBOX_DEFAULT
HelixGenesisLab_Finish:
	releaseall
	end

HelixGenesisLab_Text_Welcome:
	.string "Welcome to the HELIX laboratory!\n"
	.string "Your journey begins with a new life.\p"
	.string "First, talk to the receptionist\n"
	.string "or use the computer to the north.\p"
	.string "Register, analyze, prepare, nurture:\n"
	.string "you take part in every step.$"
HelixGenesisLab_Text_Stay:
	.string "Your first companion is born here.\n"
	.string "Reception can help with the next step.\p"
	.string "You can save and return later.\n"
	.string "There is no need to wait real days.$"
HelixGenesisLab_Text_Reception:
	.string "I am LIA. I look after registration.\n"
	.string "Your profile can change with you.$"
HelixGenesisLab_Text_Soul:
	.string "Your SOUL profile is your choice.\n"
	.string "DNA does not define who you are.\p"
	.string "What will you bring to this journey?\n"
	.string "You can edit your profile later.$"
HelixGenesisLab_Text_Dna:
	.string "Personal DNA is optional. No real\n"
	.string "file has been provided here.\p"
	.string "Would you like to see a synthetic\n"
	.string "sample from our fictional model?$"
HelixGenesisLab_Text_Synthetic:
	.string "Each virtual region has two copies.\n"
	.string "A variant can change its expression.\p"
	.string "We use synthetic data here.\n"
	.string "We do not infer health or abilities.\p"
	.string "This ROM has prepared individuals.\n"
	.string "New data needs a new game package.$"
HelixGenesisLab_Text_Registered:
	.string "Profile saved in the local record.\n"
	.string "You control all your own actions.\p"
	.string "Next, use the analysis bench north\n"
	.string "of here, to the computer's right.$"
HelixGenesisLab_Text_Geneticist:
	.string "I am ENZO. I guide the analysis.\n"
	.string "Let us explore the combinations.$"
HelixGenesisLab_Text_Analysis:
	.string "The ancient sample comes from a\n"
	.string "POKéMON lost thousands of years ago.\p"
	.string "It is not a living parent. We combine\n"
	.string "its regions with another lineage.\p"
	.string "These two viable combinations\n"
	.string "already have prepared projects.$"
HelixGenesisLab_Text_RecipeOne:
	.string "NAUTIL: ancient sample + a coastal\n"
	.string "donor with small fins.\p"
	.string "No personal DNA contribution.\n"
	.string "Origin and genome are prepared.\p"
	.string "The hybrid has its own pattern,\n"
	.string "genome, and personality.$"
HelixGenesisLab_Text_RecipeTwo:
	.string "FERRO: ancient sample + a reedland\n"
	.string "donor with slender gills.\p"
	.string "Includes a SYNTHETIC contribution.\n"
	.string "Accepting uses this fictional example.\p"
	.string "The blend creates a new individual,\n"
	.string "not just a different color.$"
HelixGenesisLab_Text_ConfirmRecipe:
	.string "Choose this project? You can review\n"
	.string "your choice before final preparation.$"
HelixGenesisLab_Text_RecipeSelected:
	.string "Project selected. Your record keeps\n"
	.string "this choice without creating another.\p"
	.string "Use the preparation terminal below,\n"
	.string "on the left wall.$"
HelixGenesisLab_Text_Depth:
	.string "Virtual regions hold variants.\n"
	.string "Its pattern is no average of colors.\p"
	.string "Compatibility limits combinations.\n"
	.string "Future fertility needs its own rule.\p"
	.string "The sample's origin is recorded.\n"
	.string "It earns no XP as a living parent would.$"
HelixGenesisLab_Text_LockedRecipe:
	.string "{STR_VAR_1} already has a fixed project.\n"
	.string "Preparation preserves its identity.\p"
	.string "Reopening the same record does not\n"
	.string "create a different life.$"
HelixGenesisLab_Text_Prepare:
	.string "Prepare {STR_VAR_1}'s genome?\n"
	.string "This step makes your choice final.\p"
	.string "The terminal checks origin, variants,\n"
	.string "and the project accepted for this ROM.$"
HelixGenesisLab_Text_Prepared:
	.string "Origin checked. Genome prepared.\n"
	.string "The project is fixed in the record.\p"
	.string "The incubator is on the right bench.\n"
	.string "Look for the caretaker.$"
HelixGenesisLab_Text_AlreadyPrepared:
	.string "Preparation is done. Nothing rerolled.\n"
	.string "The incubator holds your next step.$"
HelixGenesisLab_Text_Nursery:
	.string "I am INA. I guide the birth and\n"
	.string "care for your companion afterward.$"
HelixGenesisLab_Text_Incubate:
	.string "Start the incubation cycle?\n"
	.string "It finishes during this session.\p"
	.string "The origin and genome are fixed.\n"
	.string "Saving and returning changes nothing.$"
HelixGenesisLab_Text_Incubated:
	.string "Cycle stable. The cradle lights up.\n"
	.string "Your first companion is ready!$"
HelixGenesisLab_Text_Hatch:
	.string "Would you like to receive {STR_VAR_1}\n"
	.string "as your first companion?$"
HelixGenesisLab_Text_Born:
	.string "{STR_VAR_1} comes closer to you!\n"
	.string "Your companion has joined the party.\p"
	.string "Its hybrid origin stays on record.\n"
	.string "This life has a permanent identity.$"
HelixGenesisLab_Text_BondCurious:
	.string "Your curiosity opens a question:\n"
	.string "what will you discover together?\p"
	.string "Watch how it reacts to the world.\n"
	.string "Its personality is its own.$"
HelixGenesisLab_Text_BondCare:
	.string "Your wish to care is a beginning.\n"
	.string "Listen to what it prefers, too.\p"
	.string "Your bond grows through experience.\n"
	.string "Its personality is its own.$"
HelixGenesisLab_Text_BondPatient:
	.string "You chose to watch patiently.\n"
	.string "Let it show you its own ways.\p"
	.string "Your bond grows through experience.\n"
	.string "Its personality is its own.$"
HelixGenesisLab_Text_Next:
	.string "Open POKéMON, then SUMMARY to see it.\n"
	.string "Save to keep this story.\p"
	.string "NOA offers an optional practice battle.\n"
	.string "The CENTER has healing and a PC.\p"
	.string "IVO is still in LITTLEROOT.\n"
	.string "Your investigation can wait for you.$"
HelixGenesisLab_Text_AlreadyBorn:
	.string "Your companion has already been born.\n"
	.string "We do not issue the same life twice.\p"
	.string "If it is in the PC, withdraw it there.\n"
	.string "Its record and history remain.$"
HelixGenesisLab_Text_Followup:
	.string "{STR_VAR_1}'s record is safely kept.\n"
	.string "Origin, project, and birth stay linked.\p"
	.string "Would you like to rest and heal now?\n"
	.string "This care does not award XP.$"
HelixGenesisLab_Text_Healed:
	.string "Party healed! Experiences change\n"
	.string "progress, not identity.$"
HelixGenesisLab_Text_NeedRegister:
	.string "First, choose your SOUL profile at\n"
	.string "reception or the computer to the north.$"
HelixGenesisLab_Text_NeedRecipe:
	.string "Analyze the two viable combinations.\n"
	.string "The bench is at the upper right.$"
HelixGenesisLab_Text_NeedPreparation:
	.string "Your project still needs preparation.\n"
	.string "Use the terminal on the left wall.$"
HelixGenesisLab_Text_NeedIncubator:
	.string "Your project is ready in the cradle.\n"
	.string "Use the incubator on the right bench.$"
HelixGenesisLab_Text_Cancel:
	.string "That is fine. No life has been issued.\n"
	.string "Your last completed step stays saved.$"
HelixGenesisLab_Text_Full:
	.string "Your party is full. Your companion\n"
	.string "waits unchanged, without duplication.$"
HelixGenesisLab_Text_Invalid:
	.string "The record does not match the project.\n"
	.string "We have kept your data unchanged.$"
HelixGenesisLab_Text_Rival:
	.string "NOA: My partner has its own origin.\n"
	.string "Would you like to practice together?\p"
	.string "It is optional. We heal everyone after.\n"
	.string "There is no prize or wager.$"
HelixGenesisLab_Text_RivalWait:
	.string "NOA: Help your first companion hatch.\n"
	.string "Our practice battle can wait.$"
HelixGenesisLab_Text_RivalDone:
	.string "NOA: Our practice is on record!\n"
	.string "We keep our same companions.\p"
	.string "A rematch is not prepared yet.\n"
	.string "You are free to keep investigating.$"
HelixGenesisLab_Text_RivalHeal:
	.string "NOA: Let us care for the party first.\n"
	.string "INA can heal your companions.$"
HelixGenesisLab_Text_RivalDefeat:
	.string "We learned together!\n"
	.string "Your partner found its rhythm.$"
HelixGenesisLab_Text_RivalVictory:
	.string "Let us take care of everyone.\n"
	.string "You can try again.$"
HelixGenesisLab_Text_RivalAfter:
	.string "NOA: Party healed. The experience\n"
	.string "and result stay in our history.\p"
	.string "Practice never blocks your journey.$"

@ The only prepared living-parent cross. Preview/cancel never call admission.
HelixGenesisLab_Cross:
	special GetHelixLabLanguage
	copyvar VAR_TEMP_2, VAR_RESULT
	special GetHelixCrossState
	switch VAR_RESULT
	case 0, HelixGenesisLab_CrossInvalid
	case 2, HelixGenesisLab_CrossBorn
	case 3, HelixGenesisLab_CrossOther
	case 4, HelixGenesisLab_CrossWait
	case 5, HelixGenesisLab_CrossBoxed
	case 6, HelixGenesisLab_CrossHeal
	case 7, HelixGenesisLab_CrossFull
	case 8, HelixGenesisLab_CrossMissing
	case 9, HelixGenesisLab_CrossLocked
	showmonpic SPECIES_HELIX_CHILD, 10, 3
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossPreviewPT
	msgbox HelixGenesisLab_Text_CrossPreviewEN, MSGBOX_DEFAULT
	msgbox HelixGenesisLab_Text_CrossConfirmEN, MSGBOX_YESNO
	goto HelixGenesisLab_CrossChoice
HelixGenesisLab_CrossPreviewPT:
	msgbox HelixGenesisLab_Text_CrossPreviewPT, MSGBOX_DEFAULT
	msgbox HelixGenesisLab_Text_CrossConfirmPT, MSGBOX_YESNO
HelixGenesisLab_CrossChoice:
	hidemonpic
	goto_if_ne VAR_RESULT, YES, HelixGenesisLab_CrossCancel
	special AdmitHelixCross
	goto_if_ne VAR_RESULT, 1, HelixGenesisLab_Cross
	playfanfare MUS_OBTAIN_ITEM
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossSuccessPT
	msgbox HelixGenesisLab_Text_CrossSuccessEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_CrossSuccessWait
HelixGenesisLab_CrossSuccessPT:
	msgbox HelixGenesisLab_Text_CrossSuccessPT, MSGBOX_DEFAULT
HelixGenesisLab_CrossSuccessWait:
	waitfanfare
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossInvalid:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossInvalidPT
	msgbox HelixGenesisLab_Text_CrossInvalidEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossInvalidPT:
	msgbox HelixGenesisLab_Text_CrossInvalidPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossBorn:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossBornPT
	msgbox HelixGenesisLab_Text_CrossBornEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossBornPT:
	msgbox HelixGenesisLab_Text_CrossBornPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossOther:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossOtherPT
	msgbox HelixGenesisLab_Text_CrossOtherEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossOtherPT:
	msgbox HelixGenesisLab_Text_CrossOtherPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossWait:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossWaitPT
	msgbox HelixGenesisLab_Text_CrossWaitEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossWaitPT:
	msgbox HelixGenesisLab_Text_CrossWaitPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossBoxed:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossBoxedPT
	msgbox HelixGenesisLab_Text_CrossBoxedEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossBoxedPT:
	msgbox HelixGenesisLab_Text_CrossBoxedPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossHeal:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossHealPT
	msgbox HelixGenesisLab_Text_CrossHealEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossHealPT:
	msgbox HelixGenesisLab_Text_CrossHealPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossFull:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossFullPT
	msgbox HelixGenesisLab_Text_CrossFullEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossFullPT:
	msgbox HelixGenesisLab_Text_CrossFullPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossMissing:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossMissingPT
	msgbox HelixGenesisLab_Text_CrossMissingEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossMissingPT:
	msgbox HelixGenesisLab_Text_CrossMissingPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossCancel:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossCancelPT
	msgbox HelixGenesisLab_Text_CrossCancelEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossCancelPT:
	msgbox HelixGenesisLab_Text_CrossCancelPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_Text_CrossInvalidEN:
	.string "This family record needs a check.\nNothing has been changed.$"
HelixGenesisLab_Text_CrossInvalidPT:
	.string "O registro precisa ser conferido.\nNada foi alterado.$"
HelixGenesisLab_Text_CrossBornEN:
	.string "CORAL has already joined your story!\nThis birth cannot happen twice.\pNAUTIL and REVA keep their birth XP.\nFind CORAL in your party or PC.$"
HelixGenesisLab_Text_CrossBornPT:
	.string "CORAL ja faz parte da sua historia!\nEste nascimento acontece uma so vez.\pNAUTIL e REVA mantem o XP recebido.\nVeja CORAL na equipe ou no PC.$"
HelixGenesisLab_Text_CrossOtherEN:
	.string "FERRO has no prepared cross yet.\nThis cradle pairs NAUTIL with REVA.\pYour companion stays with you.\nMore families await future research.$"
HelixGenesisLab_Text_CrossOtherPT:
	.string "FERRO ainda nao tem cruzamento pronto.\nEste berco combina NAUTIL com REVA.\pSeu companheiro continua com voce.\nOutras familias aguardam pesquisa.$"
HelixGenesisLab_Text_CrossWaitEN:
	.string "Welcome your first companion first.\nThen we can study a new family.$"
HelixGenesisLab_Text_CrossWaitPT:
	.string "Receba seu primeiro companheiro.\nDepois vamos estudar uma nova familia.$"
HelixGenesisLab_Text_CrossBoxedEN:
	.string "NAUTIL is resting in the PC.\nWithdraw it to join REVA here.\pCORAL will wait for you.\nNothing has been born or rewarded.$"
HelixGenesisLab_Text_CrossBoxedPT:
	.string "NAUTIL esta descansando no PC.\nRetire-o para encontrar REVA aqui.\pCORAL vai esperar por voce.\nNada nasceu nem recebeu recompensa.$"
HelixGenesisLab_Text_CrossHealEN:
	.string "NAUTIL needs care before this birth.\nRest with INA, then try again.\pCORAL will wait unchanged.\nNo birth XP has been awarded.$"
HelixGenesisLab_Text_CrossHealPT:
	.string "NAUTIL precisa de cuidados primeiro.\nDescanse com INA e tente de novo.\pCORAL vai esperar sem mudancas.\nNinguem ganhou XP de nascimento.$"
HelixGenesisLab_Text_CrossFullEN:
	.string "Make one free place in your party.\nThe CENTER PC can help.\pCORAL will wait unchanged.\nNo birth XP has been awarded.$"
HelixGenesisLab_Text_CrossFullPT:
	.string "Abra um lugar na sua equipe.\nO PC do CENTRO pode ajudar.\pCORAL vai esperar sem mudancas.\nNinguem ganhou XP de nascimento.$"
HelixGenesisLab_Text_CrossMissingEN:
	.string "We cannot find your NAUTIL.\nBring your original companion here.\pIts identity is safely kept.\nWe will never create a replacement.$"
HelixGenesisLab_Text_CrossMissingPT:
	.string "Nao encontramos seu NAUTIL.\nTraga seu companheiro original.\pSua identidade continua registrada.\nNao vamos criar uma copia.$"
HelixGenesisLab_Text_CrossCancelEN:
	.string "Take your time. CORAL will wait.\nNo birth or XP reward happened.\pReturn to this cradle to continue.\nThe same family will be waiting.$"
HelixGenesisLab_Text_CrossCancelPT:
	.string "Tudo bem. CORAL vai esperar.\nNao houve nascimento nem XP.\pVolte a este berco para continuar.\nA mesma familia estara esperando.$"
HelixGenesisLab_Text_CrossPreviewEN:
	.string "NAUTIL + REVA can welcome CORAL!\nNOA brings REVA, a living parent.\pCORAL has a spiral shell and a long,\nsplit tail: traits from both parents.\pThis is one prepared family.\nEach parent gains 125 XP at birth.$"
HelixGenesisLab_Text_CrossPreviewPT:
	.string "NAUTIL + REVA podem receber CORAL!\nNOA traz REVA, um progenitor vivo.\pCORAL tem concha espiral e uma longa\ncauda dividida: tracos dos dois.\pEsta e uma familia preparada.\nCada progenitor ganha 125 XP uma vez.$"
HelixGenesisLab_Text_CrossConfirmEN:
	.string "Welcome CORAL into your party now?\nNOA keeps REVA as their companion.$"
HelixGenesisLab_Text_CrossConfirmPT:
	.string "Receber CORAL na sua equipe agora?\nREVA continua como companheiro de NOA.$"
HelixGenesisLab_Text_CrossSuccessEN:
	.string "CORAL joins your party!\nNAUTIL and REVA each gained 125 XP.\pCheck its birthday on ORIGIN.\nSave normally to keep this new life.\pPOKeDEX: R opens the companion sheet.\nSTART switches between your family.$"
HelixGenesisLab_Text_CrossSuccessPT:
	.string "CORAL entrou na sua equipe!\nNAUTIL e REVA ganharam 125 XP cada.\pVeja a data de nascimento em ORIGEM.\nSalve para guardar esta nova vida.\pPOKeDEX: R abre a ficha do companheiro.\nSTART alterna entre sua familia.$"

HelixGenesisLab_CrossLocked:
	goto_if_eq VAR_TEMP_2, 1, HelixGenesisLab_CrossLockedPT
	msgbox HelixGenesisLab_Text_CrossLockedEN, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_CrossLockedPT:
	msgbox HelixGenesisLab_Text_CrossLockedPT, MSGBOX_DEFAULT
	goto HelixGenesisLab_Finish
HelixGenesisLab_Text_CrossLockedEN:
	.string "Keep discovering your first partner.\n"
	.string "New families should be rare.\p"
	.string "CORAL's later research journey\n"
	.string "is not available yet.\p"
	.string "Your companion and its history stay.\n"
	.string "No birth or XP is awarded here.$"
HelixGenesisLab_Text_CrossLockedPT:
	.string "Continue conhecendo seu companheiro.\n"
	.string "Novas familias devem ser raras.\p"
	.string "A jornada de pesquisa para CORAL\n"
	.string "ainda nao esta disponivel.\p"
	.string "Seu companheiro e sua historia ficam.\n"
	.string "Nao ha nascimento nem XP aqui.$"
