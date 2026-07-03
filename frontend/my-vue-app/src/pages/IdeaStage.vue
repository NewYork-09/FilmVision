<script setup>
import { onMounted, inject, watch } from 'vue'
import Footer from '@/components/Footer.vue'

const currentUser    = inject('currentUser',    null)
const openAuthModal  = inject('openAuthModal',  () => {})

onMounted(() => {
  // Point to Flask backend. Set VITE_API_URL in your .env file to override.
  // e.g. VITE_API_URL=http://localhost:5000
  window.FILMVISION_API = import.meta.env.VITE_API_URL || ''
  // Expose to global scope so the vanilla-JS analyze() can read auth state
  window._fvGetCurrentUser = () => currentUser?.value || null
  window._fvOpenAuthModal  = () => openAuthModal()
})

// Watch for auth state changes
watch(currentUser, (newUser, oldUser) => {
  // User just logged in (was null, now has value)
  if (newUser && !oldUser) {
    // Refresh the saved list so it shows immediately without page reload
    window.dispatchEvent(new CustomEvent('fv-user-logged-in'));
  }
  // User just logged out (had value, now null)
  if (!newUser && oldUser) {
    // Clear form panel inputs
    _clearFormPanel();
    // Clear results panel
    _clearResultsPanel();
  }
}, { deep: true })

function _clearFormPanel() {
  // Text fields
  const storyPitch = document.getElementById('story_pitch');
  if (storyPitch) storyPitch.value = '';
  const themeText = document.getElementById('theme-input-text');
  if (themeText) themeText.value = '';

  // Multi-select fields — deselect all by calling toggleOption on each selected option
  const multiFields = ['genre','tone','target_audience','time_period','casting_category','distribution_goal','film_purpose','secondary_genre'];
  multiFields.forEach(field => {
    const dropdown = document.getElementById('dropdown-' + field);
    if (dropdown && typeof window.toggleOption === 'function') {
      // Click all selected options to deselect them
      dropdown.querySelectorAll('.multi-select-option.selected').forEach(opt => {
        const onclickAttr = opt.getAttribute('onclick') || '';
        const match = onclickAttr.match(/toggleOption\('[^']+',this,'([^']+)'\)/);
        if (match) window.toggleOption(field, opt, match[1]);
      });
    }
  });

  // Single-select fields
  if (typeof window.setSingle === 'function') {
    window.setSingle('budget_range', '');
    window.setSingle('production_schedule', '');
  }

  // Market scope — reset to international (default)
  if (typeof window.setScope === 'function') window.setScope('international');

  // Profit toggle — reset to Yes (default)
  if (typeof window.setProfit === 'function') window.setProfit(true);
}

function _clearResultsPanel() {
  const panel = document.getElementById('results');
  if (!panel) return;
  panel.innerHTML = `
    <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:8rem;gap:1rem;color:#888;text-align:center;">
      <div style="background:#f2f2f2;border-radius:16px;padding:3rem 2.1rem 2.1rem 2.1rem;display:flex;flex-direction:column;align-items:center;gap:1rem;max-width:340px;">
        <div style="font-size:3.5rem;opacity:0.3;">🎬</div>
        <h3 style="font-family:'Inria Serif',serif;font-size:1.5rem;color:#888;font-style:italic;">Ready to analyze your film</h3>
        <p style="font-family:'Assistant',sans-serif;font-size:0.72rem;letter-spacing:0.1em;max-width:280px;line-height:1.8;">Fill in your project details on the left and click Analyze to get strategic insights, similar films, and AI-powered recommendations.</p>
      </div>
    </div>`;
  // Remove budget recommender block if present
  const budgetBlock = document.getElementById('budget-rec-block');
  if (budgetBlock) budgetBlock.parentNode.removeChild(budgetBlock);
}
</script>

<template>
  <div class="fv-wrap" ref="fvRoot">

<main>
  <!-- FORM PANEL -->
  <aside class="form-panel">
    <div class="section-label">Project Details</div>

    <div class="field-group">
      <label style="display:flex;align-items:center;justify-content:space-between;">
        <span>Story Pitch <span class="required-star">*</span></span>
        <button type="button" class="pitch-expand-btn" @click="pitchModalOpen = true" title="Expand">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
          Expand
        </button>
      </label>
      <textarea id="story_pitch" placeholder="Brief logline or synopsis of your film idea..."></textarea>
    </div>

    <!-- Story Pitch expand modal -->
    <Teleport to="body">
      <div v-if="pitchModalOpen" class="pitch-modal-overlay" @mousedown.self="pitchModalOpen = false">
        <div class="pitch-modal">
          <div class="pitch-modal-header">
            <span class="pitch-modal-title">Story Pitch</span>
            <button class="pitch-modal-close" @click="pitchModalOpen = false">&#10005;</button>
          </div>
          <textarea
            class="pitch-modal-textarea"
            placeholder="Brief logline or synopsis of your film idea..."
            :value="pitchModalValue"
            @input="syncPitch($event)"
          ></textarea>
        </div>
      </div>
    </Teleport>

    <!-- Main Theme — free-text field -->
    <div class="field-group">
      <label>Main Theme <span class="required-star">*</span> <span style="font-size:0.6rem;color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">(use commas to separate multiple ideas)</span></label>
      <textarea id="theme-input-text" placeholder="e.g. Redemption, Corruption, Identity crisis, The cost of ambition..." style="min-height:80px;height:80px;resize:vertical;"></textarea>
    </div>

    <div class="two-col">
      <!-- FEATURE 5: Multi-select Genre -->
      <div class="field-group">
        <label>Genre <span class="required-star">*</span></label>
        <div class="multi-select-wrapper" id="wrapper-genre">
          <div class="multi-select-display" id="display-genre" tabindex="0" onclick="toggleDropdown('genre')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('genre')">
            <span class="placeholder">Select genre(s)</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-genre">
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Action')"><span class="check"></span>Action</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Adventure')"><span class="check"></span>Adventure</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Animation')"><span class="check"></span>Animation</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Comedy')"><span class="check"></span>Comedy</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Crime')"><span class="check"></span>Crime</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Documentary')"><span class="check"></span>Documentary</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Drama')"><span class="check"></span>Drama</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Fantasy')"><span class="check"></span>Fantasy</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Horror')"><span class="check"></span>Horror</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Mystery')"><span class="check"></span>Mystery</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Political Drama')"><span class="check"></span>Politics</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Romance')"><span class="check"></span>Romance</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Science Fiction')"><span class="check"></span>Science Fiction</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Slice of Life')"><span class="check"></span>Slice of Life</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Thriller')"><span class="check"></span>Thriller</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'War')"><span class="check"></span>War</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Western')"><span class="check"></span>Western</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Psychological')"><span class="check"></span>Psychological</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Philosophical')"><span class="check"></span>Philosophical</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Social Commentary')"><span class="check"></span>Social Commentary</div>
            <div class="multi-select-option" onclick="toggleOption('genre',this,'Arthouse')"><span class="check"></span>Arthouse</div>
          </div>
        </div>
      </div>

      <!-- FEATURE 5: Multi-select Tone -->
        <div class="field-group">
          <label>Tone <span class="required-star">*</span></label>
          <div class="multi-select-wrapper" id="wrapper-tone">
            <div class="multi-select-display" id="display-tone" tabindex="0" onclick="toggleDropdown('tone')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('tone')">
              <span class="placeholder">Select tone(s)</span>
              <span class="multi-select-arrow">&#9662;</span>
            </div>
            <div class="multi-select-dropdown" id="dropdown-tone">
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Uplifting')"><span class="check"></span>Uplifting</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Dark')"><span class="check"></span>Dark</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Humorous')"><span class="check"></span>Humorous</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Dramatic')"><span class="check"></span>Dramatic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Adventurous')"><span class="check"></span>Adventurous</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Romantic')"><span class="check"></span>Romantic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Suspenseful')"><span class="check"></span>Suspenseful</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Satirical')"><span class="check"></span>Satirical</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Experimental')"><span class="check"></span>Experimental</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Surreal')"><span class="check"></span>Surreal</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Nostalgic')"><span class="check"></span>Nostalgic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Gritty')"><span class="check"></span>Gritty</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Realistic')"><span class="check"></span>Realistic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Thought-provoking')"><span class="check"></span>Thought-Provoking</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Melancholic')"><span class="check"></span>Melancholic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Tense')"><span class="check"></span>Tense</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Ambiguous')"><span class="check"></span>Ambiguous</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Poetic')"><span class="check"></span>Poetic</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Whimsical')"><span class="check"></span>Whimsical</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Cynical')"><span class="check"></span>Cynical</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Intimate')"><span class="check"></span>Intimate</div>
              <div class="multi-select-option" onclick="toggleOption('tone',this,'Unsettling')"><span class="check"></span>Unsettling</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Secondary Genre — subtle tonal hints, not the main genre -->
      <div class="field-group" style="margin-top:-0.5rem;">
        <label style="font-size:0.65rem;opacity:0.7;">Tonal Hint <span style="font-size:0.6rem;color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0">(e.g. this is a Drama but with hints of...)</span></label>
        <div class="multi-select-wrapper" id="wrapper-secondary_genre">
          <div class="multi-select-display" id="display-secondary_genre" tabindex="0" onclick="toggleDropdown('secondary_genre')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('secondary_genre')" style="opacity:0.8;">
            <span class="placeholder">Hints of... (optional)</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-secondary_genre">
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Comedy')"><span class="check"></span>hints of Comedy</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Romance')"><span class="check"></span>hints of Romance</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Drama')"><span class="check"></span>hints of Drama</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Thriller')"><span class="check"></span>hints of Thriller</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Horror')"><span class="check"></span>hints of Horror</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Action')"><span class="check"></span>hints of Action</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Mystery')"><span class="check"></span>hints of Mystery</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Fantasy')"><span class="check"></span>hints of Fantasy</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Science Fiction')"><span class="check"></span>hints of Science Fiction</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Documentary')"><span class="check"></span>hints of Documentary</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Satire')"><span class="check"></span>hints of Satire</div>
            <div class="multi-select-option" onclick="toggleOption('secondary_genre',this,'Coming-of-Age')"><span class="check"></span>hints of Coming-of-Age</div>
          </div>
        </div>
      </div>

    <div class="two-col">
      <!-- FEATURE 5: Multi-select Target Audience -->
      <div class="field-group">
        <label>Target Audience</label>
        <div class="multi-select-wrapper" id="wrapper-target_audience">
          <div class="multi-select-display" id="display-target_audience" tabindex="0" onclick="toggleDropdown('target_audience')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('target_audience')">
            <span class="placeholder">Select audience</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-target_audience">
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'General Audience')"><span class="check"></span>General Audience</div>
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'Young Adults (18-25)')"><span class="check"></span>Young Adults (18-25)</div>
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'Adults (26-45)')"><span class="check"></span>Adults (26-45)</div>
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'Families')"><span class="check"></span>Families</div>
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'Teens')"><span class="check"></span>Teens</div>
            <div class="multi-select-option" onclick="toggleOption('target_audience',this,'Niche/Cult')"><span class="check"></span>Niche/Cult</div>
          </div>
        </div>
      </div>

      <!-- FEATURE 5: Multi-select Time Period -->
      <div class="field-group">
        <label>Time Period</label>
        <div class="multi-select-wrapper" id="wrapper-time_period">
          <div class="multi-select-display" id="display-time_period" tabindex="0" onclick="toggleDropdown('time_period')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('time_period')">
            <span class="placeholder">Select period(s)</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-time_period">
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'Contemporary')"><span class="check"></span>Contemporary</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'1970s')"><span class="check"></span>1970s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'1980s')"><span class="check"></span>1980s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'1990s')"><span class="check"></span>1990s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'2000s')"><span class="check"></span>2000s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'2010s')"><span class="check"></span>2010s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'2020s')"><span class="check"></span>2020s</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'Period Piece')"><span class="check"></span>Period Piece</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'Future/Sci-Fi')"><span class="check"></span>Future/Sci-Fi</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'Post-Apocalyptic')"><span class="check"></span>Post-Apocalyptic</div>
            <div class="multi-select-option" onclick="toggleOption('time_period',this,'Alternate World / Universe')"><span class="check"></span>Alternate World / Universe</div>
          </div>
        </div>
      </div>
    </div>

    <div class="section-label" style="margin-top:1rem;color:#FFD700 !important;">Production</div>

    <div class="field-group">
        <label>Budget Range</label>
        <div class="multi-select-wrapper" id="wrapper-budget_range">
          <div class="single-select-display" id="display-budget_range" tabindex="0" onclick="toggleSingleDropdown('budget_range')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleSingleDropdown('budget_range')">
            <span class="placeholder" id="val-budget_range">Select budget</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-budget_range">
            <div class="multi-select-option" onclick="setSingle('budget_range','')"><span class="check"></span>— None —</div>
            <div class="multi-select-option" onclick="setSingle('budget_range','Micro (<$1M)')"><span class="check"></span>Micro (&lt;$1M)</div>
            <div class="multi-select-option" onclick="setSingle('budget_range','Low ($1M-$10M)')"><span class="check"></span>Low (1M-10M)</div>
            <div class="multi-select-option" onclick="setSingle('budget_range','Mid ($10M-$50M)')"><span class="check"></span>Mid (10M-50M)</div>
            <div class="multi-select-option" onclick="setSingle('budget_range','High ($50M-$150M)')"><span class="check"></span>High (50M-150M)</div>
            <div class="multi-select-option" onclick="setSingle('budget_range','Blockbuster ($150M+)')"><span class="check"></span>Blockbuster (150M+)</div>
          </div>
        </div>
        <input type="hidden" id="budget_range" value="">
      </div>

      <div class="field-group">
        <label>Production Schedule</label>
        <div class="multi-select-wrapper" id="wrapper-production_schedule">
          <div class="single-select-display" id="display-production_schedule" tabindex="0" onclick="toggleSingleDropdown('production_schedule')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleSingleDropdown('production_schedule')">
            <span class="placeholder" id="val-production_schedule">Select schedule</span>
            <span class="multi-select-arrow">&#9662;</span>
          </div>
          <div class="multi-select-dropdown" id="dropdown-production_schedule">
            <div class="multi-select-option" onclick="setSingle('production_schedule','')"><span class="check"></span>— None —</div>
            <div class="multi-select-option" onclick="setSingle('production_schedule','Under 3 months')"><span class="check"></span>Under 3 months</div>
            <div class="multi-select-option" onclick="setSingle('production_schedule','3–6 months')"><span class="check"></span>3–6 months</div>
            <div class="multi-select-option" onclick="setSingle('production_schedule','6–12 months')"><span class="check"></span>6–12 months</div>
            <div class="multi-select-option" onclick="setSingle('production_schedule','12–24 months')"><span class="check"></span>12–24 months</div>
            <div class="multi-select-option" onclick="setSingle('production_schedule','24+ months')"><span class="check"></span>24+ months</div>
          </div>
        </div>
        <input type="hidden" id="production_schedule" value="">
      </div>

    <!-- FEATURE 5: Multi-select Casting Category -->
    <div class="field-group">
      <label>Casting Category</label>
      <div class="multi-select-wrapper" id="wrapper-casting_category">
        <div class="multi-select-display" id="display-casting_category" tabindex="0" onclick="toggleDropdown('casting_category')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('casting_category')">
          <span class="placeholder">Select casting</span>
          <span class="multi-select-arrow">&#9662;</span>
        </div>
        <div class="multi-select-dropdown" id="dropdown-casting_category">
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'A-list Stars')"><span class="check"></span>A-list Stars</div>
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'Established Mid-Tier')"><span class="check"></span>Established Mid-Tier</div>
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'Up-and-coming')"><span class="check"></span>Up-and-coming</div>
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'Unknown/Non-professional')"><span class="check"></span>Unknown/Non-professional</div>
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'Mixed (Stars + Newcomers)')"><span class="check"></span>Mixed (Stars + Newcomers)</div>
          <div class="multi-select-option" onclick="toggleOption('casting_category',this,'Animated/Voice Cast')"><span class="check"></span>Animated/Voice Cast</div>
        </div>
      </div>
    </div>

    <div class="section-label" style="margin-top:1rem;color:#FFD700 !important;">Goals & Intent</div>

    <!-- Market Scope -->
    <div class="field-group">
      <label>Market Scope</label>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap;" id="market-scope-group">
        <button type="button" class="scope-btn active" data-scope="international" onclick="setScope('international')">🌍 International</button>
        <button type="button" class="scope-btn" data-scope="filipino" onclick="setScope('filipino')">🇵🇭 Filipino</button>
        <button type="button" class="scope-btn" data-scope="mixed" onclick="setScope('mixed')">🌐 Mixed</button>
      </div>
    </div>

    <!-- Distribution Goal multi-select -->
    <div class="field-group">
      <label>Distribution Goal</label>
      <div class="multi-select-wrapper" id="wrapper-distribution_goal">
        <div class="multi-select-display" id="display-distribution_goal" tabindex="0" onclick="toggleDropdown('distribution_goal')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('distribution_goal')">
          <span class="placeholder">How do you want to release it?</span>
          <span class="multi-select-arrow">&#9662;</span>
        </div>
        <div class="multi-select-dropdown" id="dropdown-distribution_goal">
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Major Theatrical Release')"><span class="check"></span>Major Theatrical Release</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Indie / Film Festival')"><span class="check"></span>Indie / Film Festival</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Streaming Platform')"><span class="check"></span>Streaming Platform</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Online / Social Media')"><span class="check"></span>Online / Social Media</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'School / Academic Project')"><span class="check"></span>School / Academic Project</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Community / Local Screening')"><span class="check"></span>Community / Local Screening</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Niche Audience / Cult')"><span class="check"></span>Niche Audience / Cult</div>
          <div class="multi-select-option" onclick="toggleOption('distribution_goal',this,'Not Decided Yet')"><span class="check"></span>Not Decided Yet</div>
        </div>
      </div>
    </div>

    <!-- Film Purpose multi-select -->
    <div class="field-group">
      <label>Film Purpose</label>
      <div class="multi-select-wrapper" id="wrapper-film_purpose">
        <div class="multi-select-display" id="display-film_purpose" tabindex="0" onclick="toggleDropdown('film_purpose')" onkeydown="if(event.key==='Enter'||event.key===' ')toggleDropdown('film_purpose')">
          <span class="placeholder">What is this film for?</span>
          <span class="multi-select-arrow">&#9662;</span>
        </div>
        <div class="multi-select-dropdown" id="dropdown-film_purpose">
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Pure Entertainment')"><span class="check"></span>Pure Entertainment</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Send a Social Message')"><span class="check"></span>Send a Social Message</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Artistic Expression')"><span class="check"></span>Artistic Expression</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Academic / School Requirement')"><span class="check"></span>Academic / School Requirement</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Build a Portfolio')"><span class="check"></span>Build a Portfolio</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Just for Fun')"><span class="check"></span>Just for Fun</div>
          <div class="multi-select-option" onclick="toggleOption('film_purpose',this,'Raise Awareness')"><span class="check"></span>Raise Awareness</div>
        </div>
      </div>
    </div>

    <!-- Profit toggle -->
    <div class="field-group" style="margin-top:0.5rem;">
      <label>Aiming to Generate Profit?</label>
      <div style="display:flex;gap:0.6rem;margin-top:0.2rem;">
        <button type="button" class="profit-btn active" id="profit-yes" onclick="setProfit(true)">💰 Yes</button>
        <button type="button" class="profit-btn" id="profit-no" onclick="setProfit(false)">🎨 No, Not the Goal</button>
      </div>
    </div>

    <button class="analyze-btn" onclick="analyze()">
      <div class="btn-text">
        Analyze Film
      </div>
    </button>

    <!-- ── SAVED ANALYSES (logged-in users only) ──────────────────── -->
    <div v-if="currentUser" class="saved-section">
      <div class="section-label" style="margin-top:2rem;color:#FFD700 !important;">Saved Analyses</div>
      <div v-if="savedList.length === 0" class="saved-empty">No saved analyses yet. Run an analysis and save the results.</div>
      <div v-else class="saved-list">
        <div
          v-for="item in savedList"
          :key="item.id"
          class="saved-item"
        >
          <div class="saved-item-main" @click="loadSavedResult(item.id)">
            <div class="saved-item-title">{{ item.title }}</div>
            <div class="saved-item-meta">{{ item.genre }} &middot; {{ item.saved_at ? item.saved_at.slice(0,10) : '' }}</div>
            <div class="saved-item-pitch">{{ item.pitch }}</div>
          </div>
          <button class="saved-item-del" @click.stop="deleteSavedResult(item.id)" title="Delete">&#10005;</button>
        </div>
      </div>
    </div>
    <div v-else class="saved-section saved-guest">
      <div class="saved-guest-text">
        <span>&#128190;</span> <router-link to="#" @click.prevent="openAuthModal()">Log in</router-link> to save and revisit your analyses.
      </div>
    </div>
  </aside>

  <!-- RESULTS PANEL -->
  <section class="results-panel" id="results">
    <div class="empty-state" id="empty-state">
      <div class="empty-state-card">
        <div class="empty-icon">🎬</div>
        <h3>Ready to analyze your film</h3>
        <p>Fill in your project details on the left and click Analyze to get strategic insights, similar films, and AI-powered recommendations.</p>
      </div>
    </div>
  </section>
</main>

<div class="loading-overlay" id="loading">
  <div class="loading-spinner"></div>
  <div class="loading-text">Analyzing your film concept...</div>
</div>
<!-- Confirmation modal -->
<div class="confirm-overlay" id="confirm-overlay">
  <div class="confirm-modal">
    <h3>Missing Optional Fields</h3>
    <p>You haven't filled in the following fields. The analysis will still run, but some metrics may be limited:</p>
    <ul class="missing-list" id="confirm-missing-list"></ul>
    <p>Do you want to continue anyway?</p>
    <div class="confirm-btns">
      <button class="confirm-btn-yes" onclick="confirmAnalyze()">Yes, Analyze</button>
      <button class="confirm-btn-no" onclick="closeConfirm()">Go Back</button>
    </div>
  </div>
</div>
    <Footer />
</div>
</template>

<script>
export default {
  name: 'IdeaStage',
  data() {
    return {
      savedList: [],
      pitchModalOpen: false,
      pitchModalValue: '',
    }
  },
  mounted() {
    // Inject Google Fonts if not already present
    if (!document.getElementById('fv-fonts')) {
      const l = document.createElement('link');
      l.id = 'fv-fonts'; l.rel = 'stylesheet';
      l.href = 'https://fonts.googleapis.com/css2?family=Assistant:wght@300;400;500&family=Inria+Serif:ital,wght@0,300;0,400;1,300;1,400&family=Montserrat:wght@100;200;300;400&family=DM+Mono:wght@300;400;500&display=swap';
      document.head.appendChild(l);
    }
    // Decode and execute the app JS.
    // JS is base64-encoded to avoid Vue template compiler
    // choking on quotes and angle brackets inside script content.
    const encoded = 'Ci8vIOKUgOKUgOKUgCBNVUxUSS1TRUxFQ1QgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmxldCBjdXJyZW50U2NvcGUgPSAnaW50ZXJuYXRpb25hbCc7CgpsZXQgd2FudHNQcm9maXQgPSB0cnVlOwpmdW5jdGlvbiBzZXRQcm9maXQodmFsKSB7CiAgd2FudHNQcm9maXQgPSB2YWw7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3Byb2ZpdC15ZXMnKS5jbGFzc0xpc3QudG9nZ2xlKCdhY3RpdmUnLCB2YWwpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwcm9maXQtbm8nKS5jbGFzc0xpc3QudG9nZ2xlKCdhY3RpdmUnLCAhdmFsKTsKfQoKZnVuY3Rpb24gc2V0U2NvcGUoc2NvcGUpIHsKICBjdXJyZW50U2NvcGUgPSBzY29wZTsKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcuc2NvcGUtYnRuJykuZm9yRWFjaChiID0+IHsKICAgIGIuY2xhc3NMaXN0LnRvZ2dsZSgnYWN0aXZlJywgYi5kYXRhc2V0LnNjb3BlID09PSBzY29wZSk7CiAgfSk7Cn0KCmNvbnN0IG11bHRpU3RhdGUgPSB7CiAgZ2VucmU6IFtdLCB0b25lOiBbXSwgdGFyZ2V0X2F1ZGllbmNlOiBbXSwgdGltZV9wZXJpb2Q6IFtdLCBjYXN0aW5nX2NhdGVnb3J5OiBbXSwKICBkaXN0cmlidXRpb25fZ29hbDogW10sIGZpbG1fcHVycG9zZTogW10sIHNlY29uZGFyeV9nZW5yZTogW10KfTsKCmZ1bmN0aW9uIHRvZ2dsZURyb3Bkb3duKGZpZWxkKSB7CiAgY29uc3QgZHJvcGRvd24gPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZHJvcGRvd24tJyArIGZpZWxkKTsKICBjb25zdCBkaXNwbGF5ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rpc3BsYXktJyArIGZpZWxkKTsKICBjb25zdCBpc09wZW4gPSBkcm9wZG93bi5jbGFzc0xpc3QuY29udGFpbnMoJ29wZW4nKTsKICAvLyBDbG9zZSBhbGwgb3RoZXJzCiAgZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnLm11bHRpLXNlbGVjdC1kcm9wZG93bicpLmZvckVhY2goZCA9PiBkLmNsYXNzTGlzdC5yZW1vdmUoJ29wZW4nKSk7CiAgZG9jdW1lbnQucXVlcnlTZWxlY3RvckFsbCgnLm11bHRpLXNlbGVjdC1kaXNwbGF5JykuZm9yRWFjaChkID0+IGQuY2xhc3NMaXN0LnJlbW92ZSgnb3BlbicpKTsKICBpZiAoIWlzT3BlbikgewogICAgZHJvcGRvd24uY2xhc3NMaXN0LmFkZCgnb3BlbicpOwogICAgZGlzcGxheS5jbGFzc0xpc3QuYWRkKCdvcGVuJyk7CiAgfQp9CgpmdW5jdGlvbiB0b2dnbGVPcHRpb24oZmllbGQsIGVsLCB2YWx1ZSkgewogIGNvbnN0IGFyciA9IG11bHRpU3RhdGVbZmllbGRdOwogIGNvbnN0IGlkeCA9IGFyci5pbmRleE9mKHZhbHVlKTsKICBpZiAoaWR4ID09PSAtMSkgeyBhcnIucHVzaCh2YWx1ZSk7IGVsLmNsYXNzTGlzdC5hZGQoJ3NlbGVjdGVkJyk7IGVsLnF1ZXJ5U2VsZWN0b3IoJy5jaGVjaycpLmlubmVySFRNTCA9ICcmIzEwMDAzOyc7IH0KICBlbHNlIHsgYXJyLnNwbGljZShpZHgsIDEpOyBlbC5jbGFzc0xpc3QucmVtb3ZlKCdzZWxlY3RlZCcpOyBlbC5xdWVyeVNlbGVjdG9yKCcuY2hlY2snKS50ZXh0Q29udGVudCA9ICcnOyB9CiAgcmVuZGVyVGFncyhmaWVsZCk7Cn0KCmZ1bmN0aW9uIHJlbW92ZVRhZyhmaWVsZCwgdmFsdWUpIHsKICBjb25zdCBhcnIgPSBtdWx0aVN0YXRlW2ZpZWxkXTsKICBjb25zdCBpZHggPSBhcnIuaW5kZXhPZih2YWx1ZSk7CiAgaWYgKGlkeCAhPT0gLTEpIGFyci5zcGxpY2UoaWR4LCAxKTsKICAvLyBEZXNlbGVjdCBpbiBkcm9wZG93biDigJQgbWF0Y2ggYnkgZGF0YS12YWx1ZSBhdHRyaWJ1dGUgKHJlbGlhYmxlLCB3b3JrcyBldmVuIHdoZW4gdGV4dCBkaWZmZXJzIGUuZy4gImhpbnRzIG9mIFgiKQogIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoYCNkcm9wZG93bi0ke2ZpZWxkfSAubXVsdGktc2VsZWN0LW9wdGlvbmApLmZvckVhY2gob3B0ID0+IHsKICAgIGNvbnN0IG9wdFZhbCA9IG9wdC5nZXRBdHRyaWJ1dGUoJ2RhdGEtdmFsdWUnKSB8fCBvcHQuZ2V0QXR0cmlidXRlKCdvbmNsaWNrJykubWF0Y2goL3RvZ2dsZU9wdGlvblwoJ1teJ10rJyx0aGlzLCcoW14nXSspJ1wpLyk/LlsxXTsKICAgIGlmIChvcHRWYWwgPT09IHZhbHVlKSB7CiAgICAgIG9wdC5jbGFzc0xpc3QucmVtb3ZlKCdzZWxlY3RlZCcpOwogICAgICBvcHQucXVlcnlTZWxlY3RvcignLmNoZWNrJykuaW5uZXJIVE1MID0gJyc7CiAgICB9CiAgfSk7CiAgcmVuZGVyVGFncyhmaWVsZCk7Cn0KCmZ1bmN0aW9uIHJlbmRlclRhZ3MoZmllbGQpIHsKICBjb25zdCBkaXNwbGF5ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rpc3BsYXktJyArIGZpZWxkKTsKICBjb25zdCBhcnIgPSBtdWx0aVN0YXRlW2ZpZWxkXTsKICBjb25zdCBwbGFjZWhvbGRlcnMgPSB7IGdlbnJlOiAnU2VsZWN0IGdlbnJlKHMpJywgdG9uZTogJ1NlbGVjdCB0b25lKHMpJywgdGFyZ2V0X2F1ZGllbmNlOiAnU2VsZWN0IGF1ZGllbmNlJywgdGltZV9wZXJpb2Q6ICdTZWxlY3QgcGVyaW9kKHMpJywgY2FzdGluZ19jYXRlZ29yeTogJ1NlbGVjdCBjYXN0aW5nJywgZGlzdHJpYnV0aW9uX2dvYWw6ICdIb3cgZG8geW91IHdhbnQgdG8gcmVsZWFzZSBpdD8nLCBmaWxtX3B1cnBvc2U6ICdXaGF0IGlzIHRoaXMgZmlsbSBmb3I/Jywgc2Vjb25kYXJ5X2dlbnJlOiAnSGludHMgb2YuLi4gKG9wdGlvbmFsKScgfTsKCiAgZGlzcGxheS5pbm5lckhUTUwgPSAnJzsKCiAgLy8gSGVhZGVyIHJvdzogbGFiZWwgKyBhcnJvdwogIGNvbnN0IGhlYWRlciA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogIGhlYWRlci5zZXRBdHRyaWJ1dGUoJ3N0eWxlJywgJ2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7anVzdGlmeS1jb250ZW50OnNwYWNlLWJldHdlZW47bWluLWhlaWdodDoyOHB4O3dpZHRoOjEwMCU7Jyk7CiAgY29uc3QgbGFiZWwgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50KCdzcGFuJyk7CiAgaWYgKGFyci5sZW5ndGggPT09IDApIHsKICAgIGxhYmVsLmNsYXNzTmFtZSA9ICdwbGFjZWhvbGRlcic7CiAgICBsYWJlbC50ZXh0Q29udGVudCA9IHBsYWNlaG9sZGVyc1tmaWVsZF0gfHwgJ1NlbGVjdC4uLic7CiAgfSBlbHNlIHsKICAgIGxhYmVsLnNldEF0dHJpYnV0ZSgnc3R5bGUnLCAnY29sb3I6I2U3YzQ2ODtmb250LXNpemU6MC44MnJlbTsnKTsKICAgIGxhYmVsLnRleHRDb250ZW50ID0gYXJyLmxlbmd0aCArICcgc2VsZWN0ZWQnOwogIH0KICBjb25zdCBhcnJvdyA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ3NwYW4nKTsKICBhcnJvdy5jbGFzc05hbWUgPSAnbXVsdGktc2VsZWN0LWFycm93JzsKICBhcnJvdy5pbm5lckhUTUwgPSAnJiM5NjYyOyc7CiAgaGVhZGVyLmFwcGVuZENoaWxkKGxhYmVsKTsKICBoZWFkZXIuYXBwZW5kQ2hpbGQoYXJyb3cpOwogIGRpc3BsYXkuYXBwZW5kQ2hpbGQoaGVhZGVyKTsKCiAgLy8gVGFncyBzdGFja2VkIHZlcnRpY2FsbHkKICBhcnIuZm9yRWFjaCh2ID0+IHsKICAgIGNvbnN0IHRhZyA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogICAgdGFnLnNldEF0dHJpYnV0ZSgnc3R5bGUnLCAnZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjt3aWR0aDoxMDAlO2JveC1zaXppbmc6Ym9yZGVyLWJveDtwYWRkaW5nOjAuM3JlbSAwLjVyZW07bWFyZ2luLXRvcDowLjNyZW07YmFja2dyb3VuZDpyZ2JhKDIzMSwxOTYsMTA0LDAuMSk7Ym9yZGVyOjFweCBzb2xpZCByZ2JhKDIzMSwxOTYsMTA0LDAuMjUpO2JvcmRlci1yYWRpdXM6NHB4O2NvbG9yOiNlN2M0Njg7Zm9udC1zaXplOjAuOHJlbTsnKTsKICAgIGNvbnN0IHRleHQgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50KCdzcGFuJyk7CiAgICB0ZXh0LnNldEF0dHJpYnV0ZSgnc3R5bGUnLCAnZmxleDoxO3RleHQtYWxpZ246bGVmdDsnKTsKICAgIHRleHQudGV4dENvbnRlbnQgPSB2OwogICAgY29uc3QgYnRuID0gZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgnc3BhbicpOwogICAgYnRuLnNldEF0dHJpYnV0ZSgnc3R5bGUnLCAnbWFyZ2luLWxlZnQ6YXV0bztwYWRkaW5nLWxlZnQ6MC43NXJlbTtvcGFjaXR5OjAuNjtmb250LXdlaWdodDo3MDA7Y3Vyc29yOnBvaW50ZXI7ZmxleC1zaHJpbms6MDsnKTsKICAgIGJ0bi50ZXh0Q29udGVudCA9ICd4JzsKICAgIGJ0bi5zZXRBdHRyaWJ1dGUoJ29ubW91c2Vkb3duJywgImV2ZW50LnByZXZlbnREZWZhdWx0KCk7cmVtb3ZlVGFnKCciICsgZmllbGQgKyAiJywnIiArIHYucmVwbGFjZSgvJy9nLCJcJyIpICsgIicpIik7CiAgICB0YWcuYXBwZW5kQ2hpbGQodGV4dCk7CiAgICB0YWcuYXBwZW5kQ2hpbGQoYnRuKTsKICAgIGRpc3BsYXkuYXBwZW5kQ2hpbGQodGFnKTsKICB9KTsKCiAgaWYgKGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkcm9wZG93bi0nICsgZmllbGQpICYmIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkcm9wZG93bi0nICsgZmllbGQpLmNsYXNzTGlzdC5jb250YWlucygnb3BlbicpKSB7CiAgICBkaXNwbGF5LmNsYXNzTGlzdC5hZGQoJ29wZW4nKTsKICB9Cn0KCi8vIENsb3NlIGRyb3Bkb3ducyB3aGVuIGNsaWNraW5nIG91dHNpZGUKZG9jdW1lbnQuYWRkRXZlbnRMaXN0ZW5lcignbW91c2Vkb3duJywgKGUpID0+IHsKICBpZiAoIWUudGFyZ2V0LmNsb3Nlc3QoJy5tdWx0aS1zZWxlY3Qtd3JhcHBlcicpKSB7CiAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcubXVsdGktc2VsZWN0LWRyb3Bkb3duJykuZm9yRWFjaChkID0+IGQuY2xhc3NMaXN0LnJlbW92ZSgnb3BlbicpKTsKICAgIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJy5tdWx0aS1zZWxlY3QtZGlzcGxheScpLmZvckVhY2goZCA9PiBkLmNsYXNzTGlzdC5yZW1vdmUoJ29wZW4nKSk7CiAgfQp9KTsKCi8vIOKUgOKUgOKUgCBNQUlOIFRIRU1FIChmcmVlLXRleHQpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApmdW5jdGlvbiBnZXRNYWluVGhlbWUoKSB7CiAgcmV0dXJuIChkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndGhlbWUtaW5wdXQtdGV4dCcpIHx8IHt9KS52YWx1ZSB8fCAnJzsKfQoKLy8g4pSA4pSA4pSAIEZJTkFOQ0lBTCArIEFVRElFTkNFICsgQ1VMVFVSQUwgU1VCLU1FVFJJQ1Mg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmZ1bmN0aW9uIGNhbGNTdWJNZXRyaWNzKGRhdGEsIHN1YlJlYXNvbnMsIHN1YlNjb3JlcykgewogIC8vIFVzZSBzZXJ2ZXItY29tcHV0ZWQgc2NvcmVzIChmdWxseSBkZXJpdmVkIGZyb20gYWxsIGlucHV0cykgd2hlbiBhdmFpbGFibGUKICBjb25zdCBnZW5yZXMgICA9IEFycmF5LmlzQXJyYXkoZGF0YS5nZW5yZSkgICAgICAgICAgICA/IGRhdGEuZ2VucmUgICAgICAgICAgICA6IFtkYXRhLmdlbnJlXS5maWx0ZXIoQm9vbGVhbik7CiAgY29uc3QgdG9uZXMgICAgPSBBcnJheS5pc0FycmF5KGRhdGEudG9uZSkgICAgICAgICAgICAgPyBkYXRhLnRvbmUgICAgICAgICAgICAgOiBbZGF0YS50b25lXS5maWx0ZXIoQm9vbGVhbik7CiAgY29uc3QgYXVkaWVuY2VzPSBBcnJheS5pc0FycmF5KGRhdGEudGFyZ2V0X2F1ZGllbmNlKSAgPyBkYXRhLnRhcmdldF9hdWRpZW5jZSAgOiBbZGF0YS50YXJnZXRfYXVkaWVuY2VdLmZpbHRlcihCb29sZWFuKTsKCiAgLy8gRmluYW5jaWFsIHNjb3JlIChudW1lcmljIG9ubHkgJm1kYXNoOyByZWFzb24gY29tZXMgZnJvbSBHcm9xKQogIGNvbnN0IGZpbmFuY2lhbFNjb3JlTWFwID0gewogICAgJ01pY3JvICg8JDFNKSc6NTUsJ0xvdyAoJDFNLSQxME0pJzo2MiwnTWlkICgkMTBNLSQ1ME0pJzo3MiwKICAgICdIaWdoICgkNTBNLSQxNTBNKSc6ODAsJ0Jsb2NrYnVzdGVyICgkMTUwTSspJzo4OAogIH07CiAgY29uc3QgZmluYW5jaWFsRGVzY01hcCA9IHsKICAgICdNaWNybyAoPCQxTSknOidMb3cgcmlzaywgbGltaXRlZCByZWFjaCcsJ0xvdyAoJDFNLSQxME0pJzonSW5kaWUgcG90ZW50aWFsLCBuaWNoZSByZXR1cm5zJywKICAgICdNaWQgKCQxME0tJDUwTSknOidTb2xpZCBtaWQtdGllciBjb21tZXJjaWFsIHJhbmdlJywnSGlnaCAoJDUwTS0kMTUwTSknOidTdHJvbmcgY29tbWVyY2lhbCBpbmZyYXN0cnVjdHVyZScsCiAgICAnQmxvY2tidXN0ZXIgKCQxNTBNKyknOidIaWdoIGludmVzdG1lbnQsIGhpZ2ggcmV0dXJuIHBvdGVudGlhbCcKICB9OwogIGNvbnN0IGZpbmFuY2lhbCA9IHsKICAgIHNjb3JlOiAoc3ViU2NvcmVzICYmIHN1YlNjb3Jlcy5maW5hbmNpYWwgIT0gbnVsbCkgPyBzdWJTY29yZXMuZmluYW5jaWFsIDogKGZpbmFuY2lhbFNjb3JlTWFwW2RhdGEuYnVkZ2V0X3JhbmdlXSB8fCA1MCksCiAgICBkZXNjOiAgZmluYW5jaWFsRGVzY01hcFtkYXRhLmJ1ZGdldF9yYW5nZV0gIHx8ICdCdWRnZXQgbm90IHNwZWNpZmllZCcsCiAgICByZWFzb246IChzdWJSZWFzb25zICYmIHN1YlJlYXNvbnMuZmluYW5jaWFsKSB8fCAnJwogIH07CgogIC8vIEF1ZGllbmNlIHNjb3JlIChudW1lcmljIG9ubHkgJm1kYXNoOyByZWFzb24gY29tZXMgZnJvbSBHcm9xKQogIGNvbnN0IGF1ZGllbmNlU2NvcmVzID0gewogICAgJ0dlbmVyYWwgQXVkaWVuY2UnOjg1LCdGYW1pbGllcyc6ODIsJ1lvdW5nIEFkdWx0cyAoMTgtMjUpJzo3OCwKICAgICdUZWVucyc6NzIsJ0FkdWx0cyAoMjYtNDUpJzo3NCwnTmljaGUvQ3VsdCc6NTgKICB9OwogIGNvbnN0IGF2Z0F1ZGllbmNlID0gKHN1YlNjb3JlcyAmJiBzdWJTY29yZXMuYXVkaWVuY2UgIT0gbnVsbCkKICAgID8gc3ViU2NvcmVzLmF1ZGllbmNlCiAgICA6IChhdWRpZW5jZXMubGVuZ3RoID8gTWF0aC5yb3VuZChhdWRpZW5jZXMucmVkdWNlKChzLGEpID0+IHMrKGF1ZGllbmNlU2NvcmVzW2FdfHw2NSksMCkvYXVkaWVuY2VzLmxlbmd0aCkgOiA2NSk7CiAgY29uc3QgYXVkaWVuY2VEZXNjID0gYXVkaWVuY2VzLmxlbmd0aCA+IDEKICAgID8gYEFjcm9zcyAke2F1ZGllbmNlcy5sZW5ndGh9IGF1ZGllbmNlIHNlZ21lbnRzYAogICAgOiAoYXVkaWVuY2VzWzBdIHx8ICdOb3Qgc3BlY2lmaWVkJyk7CgogIC8vIEN1bHR1cmFsIHNjb3JlIChudW1lcmljIG9ubHkgJm1kYXNoOyByZWFzb24gY29tZXMgZnJvbSBHcm9xKQogIGNvbnN0IGN1bHR1cmFsR2VucmVzID0gWydEcmFtYScsJ1NjaWVuY2UgRmljdGlvbicsJ1dhcicsJ0NyaW1lJywnRG9jdW1lbnRhcnknLCdGYW50YXN5J107CiAgY29uc3QgY3VsdHVyYWxUb25lcyAgPSBbJ0RhcmsnLCdFeHBlcmltZW50YWwnLCdTdXJyZWFsJywnU2F0aXJpY2FsJywnR3JpdHR5JywnRHJhbWF0aWMnXTsKICBsZXQgY3VsdHVyYWwgPSAoc3ViU2NvcmVzICYmIHN1YlNjb3Jlcy5jdWx0dXJhbCAhPSBudWxsKSA/IHN1YlNjb3Jlcy5jdWx0dXJhbCA6IDUwOwogIGlmICghc3ViU2NvcmVzIHx8IHN1YlNjb3Jlcy5jdWx0dXJhbCA9PSBudWxsKSB7CiAgICBnZW5yZXMuZm9yRWFjaChnID0+IHsgaWYgKGN1bHR1cmFsR2VucmVzLmluY2x1ZGVzKGcpKSBjdWx0dXJhbCArPSA4OyB9KTsKICAgIHRvbmVzLmZvckVhY2godCAgPT4geyBpZiAoY3VsdHVyYWxUb25lcy5pbmNsdWRlcyh0KSkgIGN1bHR1cmFsICs9IDY7IH0pOwogICAgaWYgKGRhdGEubWFpbl90aGVtZSkgY3VsdHVyYWwgKz0gMTA7CiAgICBjdWx0dXJhbCA9IE1hdGgubWluKDk1LCBjdWx0dXJhbCk7CiAgfQogIGNvbnN0IGN1bHR1cmFsRGVzYyA9IGN1bHR1cmFsPj03NSA/ICdTdHJvbmcgdGhlbWF0aWMgcmVzb25hbmNlIGV4cGVjdGVkJwogICAgICAgICAgICAgICAgICAgICAgOiBjdWx0dXJhbD49NjAgPyAnTW9kZXJhdGUgY3VsdHVyYWwgZm9vdHByaW50JwogICAgICAgICAgICAgICAgICAgICAgOiAnTGltaXRlZCBjdWx0dXJhbCBsb25nZXZpdHknOwoKICByZXR1cm4gewogICAgZmluYW5jaWFsLAogICAgYXVkaWVuY2U6IHsgc2NvcmU6IGF2Z0F1ZGllbmNlLCBkZXNjOiBhdWRpZW5jZURlc2MsIHJlYXNvbjogKHN1YlJlYXNvbnMgJiYgc3ViUmVhc29ucy5hdWRpZW5jZSkgfHwgJycgfSwKICAgIGN1bHR1cmFsOiB7IHNjb3JlOiBjdWx0dXJhbCwgICAgZGVzYzogY3VsdHVyYWxEZXNjLCAgcmVhc29uOiAoc3ViUmVhc29ucyAmJiBzdWJSZWFzb25zLmN1bHR1cmFsKSB8fCAnJyB9CiAgfTsKfQoKZnVuY3Rpb24gc2NvcmVDb2xvcihzKSB7CiAgcmV0dXJuIHMgPj0gNzAgPyAnIzRhZGU4MCcgOiBzID49IDUwID8gJyNlOGM0NmEnIDogJyNmODcxNzEnOwp9CgovLyDilIDilIDilIAgQU5BTFlaRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKbGV0IF9wZW5kaW5nQW5hbHl6ZURhdGEgPSBudWxsOwoKZnVuY3Rpb24gYnVpbGRBbmFseXplRGF0YSgpIHsKICByZXR1cm4gewogICAgc3RvcnlfcGl0Y2g6IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdG9yeV9waXRjaCcpLnZhbHVlLnRyaW0oKSwKICAgIG1haW5fdGhlbWU6IGdldE1haW5UaGVtZSgpLAogICAgYnVkZ2V0X3JhbmdlOiBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYnVkZ2V0X3JhbmdlJykudmFsdWUsCiAgICBwcm9kdWN0aW9uX3NjaGVkdWxlOiBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncHJvZHVjdGlvbl9zY2hlZHVsZScpLnZhbHVlLAogICAgZ2VucmU6IFsuLi5tdWx0aVN0YXRlLmdlbnJlXSwKICAgIHRvbmU6IFsuLi5tdWx0aVN0YXRlLnRvbmVdLAogICAgdGFyZ2V0X2F1ZGllbmNlOiBbLi4ubXVsdGlTdGF0ZS50YXJnZXRfYXVkaWVuY2VdLAogICAgdGltZV9wZXJpb2Q6IFsuLi5tdWx0aVN0YXRlLnRpbWVfcGVyaW9kXSwKICAgIGNhc3RpbmdfY2F0ZWdvcnk6IFsuLi5tdWx0aVN0YXRlLmNhc3RpbmdfY2F0ZWdvcnldLAogICAgZGlzdHJpYnV0aW9uX2dvYWw6IFsuLi5tdWx0aVN0YXRlLmRpc3RyaWJ1dGlvbl9nb2FsXSwKICAgIGZpbG1fcHVycG9zZTogWy4uLm11bHRpU3RhdGUuZmlsbV9wdXJwb3NlXSwKICAgIHNlY29uZGFyeV9nZW5yZTogWy4uLihtdWx0aVN0YXRlLnNlY29uZGFyeV9nZW5yZXx8W10pXSwKICAgIG1hcmtldF9zY29wZTogY3VycmVudFNjb3BlLAogICAgd2FudHNfcHJvZml0OiB3YW50c1Byb2ZpdCwKICB9Owp9Cgphc3luYyBmdW5jdGlvbiBydW5BbmFseXNpcyhkYXRhKSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2xvYWRpbmcnKS5jbGFzc0xpc3QuYWRkKCdhY3RpdmUnKTsKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCcuYW5hbHl6ZS1idG4nKS5kaXNhYmxlZCA9IHRydWU7CiAgdHJ5IHsKICAgIGNvbnN0IHJlc3AgPSBhd2FpdCBmZXRjaCgod2luZG93LkZJTE1WSVNJT05fQVBJIHx8ICcnKSArICcvYW5hbHl6ZScsIHsKICAgICAgbWV0aG9kOiAnUE9TVCcsCiAgICAgIGhlYWRlcnM6IHsgJ0NvbnRlbnQtVHlwZSc6ICdhcHBsaWNhdGlvbi9qc29uJyB9LAogICAgICBib2R5OiBKU09OLnN0cmluZ2lmeShkYXRhKQogICAgfSk7CiAgICBjb25zdCByZXN1bHQgPSBhd2FpdCByZXNwLmpzb24oKTsKICAgIGlmIChyZXN1bHQuZXJyb3IpIHRocm93IG5ldyBFcnJvcihyZXN1bHQuZXJyb3IpOwogICAgcmVuZGVyUmVzdWx0cyhyZXN1bHQsIGRhdGEpOwogIH0gY2F0Y2ggKGUpIHsKICAgIGFsZXJ0KCdTb21ldGhpbmcgd2VudCB3cm9uZy4gUGxlYXNlIHRyeSBhZ2Fpbi5cbicgKyAoZS5tZXNzYWdlIHx8ICcnKSk7CiAgfSBmaW5hbGx5IHsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdsb2FkaW5nJykuY2xhc3NMaXN0LnJlbW92ZSgnYWN0aXZlJyk7CiAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yKCcuYW5hbHl6ZS1idG4nKS5kaXNhYmxlZCA9IGZhbHNlOwogIH0KfQoKZnVuY3Rpb24gYW5hbHl6ZSgpIHsKICBjb25zdCBkYXRhID0gYnVpbGRBbmFseXplRGF0YSgpOwoKICAvLyDilIDilIAgUmVxdWlyZWQgZmllbGQgdmFsaWRhdGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICBjb25zdCBlcnJvcnMgPSBbXTsKICBpZiAoIWRhdGEuc3RvcnlfcGl0Y2gpIGVycm9ycy5wdXNoKHsgZmllbGQ6ICdzdG9yeV9waXRjaCcsIGxhYmVsOiAnU3RvcnkgUGl0Y2gnIH0pOwogIGlmICghZGF0YS5tYWluX3RoZW1lKSAgZXJyb3JzLnB1c2goeyBmaWVsZDogJ3RoZW1lLWlucHV0LXRleHQnLCBsYWJlbDogJ01haW4gVGhlbWUnIH0pOwogIGlmICghZGF0YS5nZW5yZS5sZW5ndGgpIGVycm9ycy5wdXNoKHsgZmllbGQ6ICdkaXNwbGF5LWdlbnJlJywgbGFiZWw6ICdHZW5yZScgfSk7CiAgaWYgKCFkYXRhLnRvbmUubGVuZ3RoKSAgZXJyb3JzLnB1c2goeyBmaWVsZDogJ2Rpc3BsYXktdG9uZScsICBsYWJlbDogJ1RvbmUnIH0pOwoKICAvLyBDbGVhciBwcmV2aW91cyBlcnJvciBzdGF0ZXMKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcuZmllbGQtZXJyb3InKS5mb3JFYWNoKGVsID0+IGVsLmNsYXNzTGlzdC5yZW1vdmUoJ2ZpZWxkLWVycm9yJykpOwoKICBpZiAoZXJyb3JzLmxlbmd0aCkgewogICAgZXJyb3JzLmZvckVhY2goZSA9PiB7CiAgICAgIGNvbnN0IGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoZS5maWVsZCk7CiAgICAgIGlmIChlbCkgZWwuY2xhc3NMaXN0LmFkZCgnZmllbGQtZXJyb3InKTsKICAgIH0pOwogICAgY29uc3QgbGFiZWxzID0gZXJyb3JzLm1hcChlID0+IGUubGFiZWwpLmpvaW4oJywgJyk7CiAgICBhbGVydCgnUGxlYXNlIGZpbGwgaW4gdGhlIHJlcXVpcmVkIGZpZWxkczogJyArIGxhYmVscyk7CiAgICByZXR1cm47CiAgfQoKICAvLyDilIDilIAgT3B0aW9uYWwgZmllbGQgY29uZmlybWF0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogIGNvbnN0IG9wdGlvbmFsX21pc3NpbmcgPSBbXTsKICBpZiAoIWRhdGEuYnVkZ2V0X3JhbmdlKSAgICAgICAgICBvcHRpb25hbF9taXNzaW5nLnB1c2goJ0J1ZGdldCBSYW5nZSAoRmluYW5jaWFsIFN1Y2Nlc3MgbWV0cmljIHdpbGwgc2hvdyBhcyB1bmRlY2lkZWQpJyk7CiAgaWYgKCFkYXRhLnRhcmdldF9hdWRpZW5jZS5sZW5ndGgpIG9wdGlvbmFsX21pc3NpbmcucHVzaCgnVGFyZ2V0IEF1ZGllbmNlIChBdWRpZW5jZSBSZWNlcHRpb24gbWV0cmljIHdpbGwgc2hvdyBhcyB1bmRlY2lkZWQpJyk7CiAgaWYgKCFkYXRhLnRpbWVfcGVyaW9kLmxlbmd0aCkgICAgb3B0aW9uYWxfbWlzc2luZy5wdXNoKCdUaW1lIFBlcmlvZCcpOwogIGlmICghZGF0YS5jYXN0aW5nX2NhdGVnb3J5Lmxlbmd0aCkgb3B0aW9uYWxfbWlzc2luZy5wdXNoKCdDYXN0aW5nIENhdGVnb3J5Jyk7CiAgaWYgKCFkYXRhLmRpc3RyaWJ1dGlvbl9nb2FsLmxlbmd0aCkgb3B0aW9uYWxfbWlzc2luZy5wdXNoKCdEaXN0cmlidXRpb24gR29hbCcpOwoKICBpZiAob3B0aW9uYWxfbWlzc2luZy5sZW5ndGgpIHsKICAgIF9wZW5kaW5nQW5hbHl6ZURhdGEgPSBkYXRhOwogICAgY29uc3QgbGlzdCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdjb25maXJtLW1pc3NpbmctbGlzdCcpOwogICAgbGlzdC5pbm5lckhUTUwgPSBvcHRpb25hbF9taXNzaW5nLm1hcChtID0+ICc8bGk+JyArIG0gKyAnPC9saT4nKS5qb2luKCcnKTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdjb25maXJtLW92ZXJsYXknKS5jbGFzc0xpc3QuYWRkKCdvcGVuJyk7CiAgICByZXR1cm47CiAgfQoKICBydW5BbmFseXNpcyhkYXRhKTsKfQoKZnVuY3Rpb24gY29uZmlybUFuYWx5emUoKSB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2NvbmZpcm0tb3ZlcmxheScpLmNsYXNzTGlzdC5yZW1vdmUoJ29wZW4nKTsKICBpZiAoX3BlbmRpbmdBbmFseXplRGF0YSkgcnVuQW5hbHlzaXMoX3BlbmRpbmdBbmFseXplRGF0YSk7Cn0KCmZ1bmN0aW9uIGNsb3NlQ29uZmlybSgpIHsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnY29uZmlybS1vdmVybGF5JykuY2xhc3NMaXN0LnJlbW92ZSgnb3BlbicpOwogIF9wZW5kaW5nQW5hbHl6ZURhdGEgPSBudWxsOwp9CgovLyDilIDilIDilIAgUkVOREVSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApmdW5jdGlvbiByZW5kZXJSZXN1bHRzKHJlc3VsdCwgZm9ybURhdGEpIHsKICBjb25zdCB7IGludGxfc3VyZmFjZSwgaW50bF9kZWVwLCBwaF9zdXJmYWNlLCBwaF9kZWVwLAogICAgICAgICAgaW50bF9maWxtcywgcGhfZmlsbXMsIHNpbWlsYXJfZmlsbXMsIHN1Y2Nlc3NfcmF0ZSwgYWlfYW5hbHlzaXMsCiAgICAgICAgICBzdWJfcmVhc29ucywgc3ViX3Njb3JlcywgbWV0aG9kLCBtYXJrZXRfc2NvcGUsIHdhbnRzX3Byb2ZpdCwKICAgICAgICAgIHN0b3J5X2FkdmljZSB9ID0gcmVzdWx0OwogIC8vIFVzZSBzZXJ2ZXItc2lkZSB3YW50c19wcm9maXQgKGF1dGhvcml0YXRpdmUpIG1lcmdlZCB3aXRoIGZvcm1EYXRhCiAgY29uc3Qgc2hvd0ZpbmFuY2lhbCA9ICh3YW50c19wcm9maXQgIT09IGZhbHNlICYmIHdhbnRzX3Byb2ZpdCAhPT0gJ2ZhbHNlJyk7CgogIC8vIEJ1aWxkIGZpbG0gY2FyZCBIVE1MIGZvciBhIGxpc3Qgb2YgZmlsbXMKICBmdW5jdGlvbiBidWlsZEZpbG1DYXJkcyhmaWxtcywgc2hvd1BIQmFkZ2UpIHsKICAgIHJldHVybiAoZmlsbXMgfHwgW10pLm1hcCgoZiwgaSkgPT4gYAogICAgICA8YSBjbGFzcz0iZmlsbS1jYXJkIHN0YWdnZXItJHtNYXRoLm1pbihpKzEsNCl9IiBocmVmPSJodHRwczovL3d3dy50aGVtb3ZpZWRiLm9yZy9tb3ZpZS8ke2YudG1kYl9pZCB8fCAnJ30iIHRhcmdldD0iX2JsYW5rIiByZWw9Im5vb3BlbmVyIj4KICAgICAgICAke2YucG9zdGVyCiAgICAgICAgICA/IGA8aW1nIGNsYXNzPSJmaWxtLXBvc3RlciIgc3JjPSIke2YucG9zdGVyfSIgYWx0PSIke2YudGl0bGV9IiBsb2FkaW5nPSJsYXp5Ii8+YAogICAgICAgICAgOiBgPGRpdiBjbGFzcz0iZmlsbS1wb3N0ZXItcGxhY2Vob2xkZXIiPiYjMTI3OTAyO++4jzwvZGl2PmB9CiAgICAgICAgPGRpdiBjbGFzcz0iZmlsbS1pbmZvIj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImZpbG0tdGl0bGUiPiR7Zi50aXRsZX0ke3Nob3dQSEJhZGdlICYmIGYuaXNfZmlsaXBpbm8gPyAnJyA6ICcnfTwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iZmlsbS1tZXRhIj4KICAgICAgICAgICAgPHNwYW4+JHtmLnJlbGVhc2VfZGF0ZX08L3NwYW4+CiAgICAgICAgICAgIDxzcGFuIGNsYXNzPSJmaWxtLXNjb3JlIj4mIzk3MzM7ICR7Zi52b3RlX2F2ZXJhZ2V9PC9zcGFuPgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICAke2YucGxvdCA/IGA8ZGl2IGNsYXNzPSJmaWxtLXBsb3QiPiR7Zi5wbG90fTwvZGl2PmAgOiAnJ30KICAgICAgICAgICR7Zi5yZWFzb24gPyBgPGRpdiBjbGFzcz0iZmlsbS1yZWFzb24tbGFiZWwiPkhvdyBpdCBDb25uZWN0czo8L2Rpdj48ZGl2IGNsYXNzPSJmaWxtLXJlYXNvbiI+JHtmLnJlYXNvbn08L2Rpdj5gIDogJyd9CiAgICAgICAgICA8ZGl2IGNsYXNzPSJmaWxtLWxpbmstaGludCI+JiMxMjgyNzk7IFZpZXcgb24gVE1EQjwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2E+CiAgICBgKS5qb2luKCcnKTsKICB9CiAgY29uc3QgcGFuZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVzdWx0cycpOwogIGNvbnN0IHJhdGVDb2xvciA9IHN1Y2Nlc3NfcmF0ZSA+PSA3MCA/ICdoaWdoJyA6IHN1Y2Nlc3NfcmF0ZSA+PSA0NSA/ICdtaWQnIDogJ2xvdyc7CiAgY29uc3QgcmF0ZUNvbG9yVmFyID0gcmF0ZUNvbG9yID09PSAnaGlnaCcgPyAnIzRhZGU4MCcgOiByYXRlQ29sb3IgPT09ICdtaWQnID8gJyNlOGM0NmEnIDogJyNmODcxNzEnOwoKICBjb25zdCBzdWIgPSBjYWxjU3ViTWV0cmljcyhmb3JtRGF0YSwgc3ViX3JlYXNvbnMsIHN1Yl9zY29yZXMpOwogIC8vIE92ZXJyaWRlIHdpdGggc2VydmVyIHNlbnRpbmVsIHZhbHVlcyBmb3IgdW5kZWNpZGVkIGZpZWxkcwogIGlmIChzdWJfc2NvcmVzICYmIHN1Yl9zY29yZXMuZmluYW5jaWFsIDwgMCkgc3ViLmZpbmFuY2lhbC5zY29yZSA9IC0xOwogIGlmIChzdWJfc2NvcmVzICYmIHN1Yl9zY29yZXMuYXVkaWVuY2UgIDwgMCkgc3ViLmF1ZGllbmNlLnNjb3JlICA9IC0xOwoKICAvLyBCdWlsZCBmaWxtIGNhcmRzIGhlbHBlcgogIGZ1bmN0aW9uIGJ1aWxkRmlsbVNlY3Rpb24oZmlsbXMsIHNob3dQSEJhZGdlLCB0aXRsZUxhYmVsLCBzdWJsYWJlbCkgewogICAgaWYgKCFmaWxtcyB8fCAhZmlsbXMubGVuZ3RoKSByZXR1cm4gJyc7CiAgICBjb25zdCBjYXJkcyA9IGZpbG1zLm1hcCgoZiwgaSkgPT4gYAogICAgICA8YSBjbGFzcz0iZmlsbS1jYXJkIHN0YWdnZXItJHtNYXRoLm1pbihpKzEsNCl9IiBocmVmPSJodHRwczovL3d3dy50aGVtb3ZpZWRiLm9yZy9tb3ZpZS8ke2YudG1kYl9pZCB8fCAnJ30iIHRhcmdldD0iX2JsYW5rIiByZWw9Im5vb3BlbmVyIj4KICAgICAgICAke2YucG9zdGVyCiAgICAgICAgICA/IGA8aW1nIGNsYXNzPSJmaWxtLXBvc3RlciIgc3JjPSIke2YucG9zdGVyfSIgYWx0PSIke2YudGl0bGV9IiBsb2FkaW5nPSJsYXp5Ii8+YAogICAgICAgICAgOiBgPGRpdiBjbGFzcz0iZmlsbS1wb3N0ZXItcGxhY2Vob2xkZXIiPiYjMTI3OTAyO++4jzwvZGl2PmB9CiAgICAgICAgPGRpdiBjbGFzcz0iZmlsbS1pbmZvIj4KICAgICAgICAgIDxkaXYgY2xhc3M9ImZpbG0tdGl0bGUiPiR7Zi50aXRsZX0ke3Nob3dQSEJhZGdlICYmIGYuaXNfZmlsaXBpbm8gPyAnJyA6ICcnfTwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0iZmlsbS1tZXRhIj48c3Bhbj4ke2YucmVsZWFzZV9kYXRlfTwvc3Bhbj48c3BhbiBjbGFzcz0iZmlsbS1zY29yZSI+JiM5NzMzOyAke2Yudm90ZV9hdmVyYWdlfTwvc3Bhbj48L2Rpdj4KICAgICAgICAgICR7Zi5wbG90ID8gYDxkaXYgY2xhc3M9ImZpbG0tcGxvdCI+JHtmLnBsb3R9PC9kaXY+YCA6ICcnfQogICAgICAgICAgJHtmLnJlYXNvbiA/IGA8ZGl2IGNsYXNzPSJmaWxtLXJlYXNvbi1sYWJlbCI+SG93IGl0IENvbm5lY3RzOjwvZGl2PjxkaXYgY2xhc3M9ImZpbG0tcmVhc29uIj4ke2YucmVhc29ufTwvZGl2PmAgOiAnJ30KICAgICAgICAgIDxkaXYgY2xhc3M9ImZpbG0tbGluay1oaW50Ij4mIzEyODI3OTsgVmlldyBvbiBUTURCPC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwvYT5gKS5qb2luKCcnKTsKICAgIHJldHVybiBgCiAgICAgIDxkaXYgY2xhc3M9ImJsb2NrLXRpdGxlIHN0YWdnZXItMiI+JHt0aXRsZUxhYmVsfQogICAgICAgICR7c3VibGFiZWwgPyBgPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZTowLjZyZW07Y29sb3I6dmFyKC0tbXV0ZWQpO2ZvbnQtd2VpZ2h0OjQwMDtsZXR0ZXItc3BhY2luZzowO3RleHQtdHJhbnNmb3JtOm5vbmU7bWFyZ2luLWxlZnQ6MC41cmVtIj4ke3N1YmxhYmVsfTwvc3Bhbj5gIDogJyd9CiAgICAgIDwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJmaWxtcy1ncmlkIHN0YWdnZXItMiI+JHtjYXJkc308L2Rpdj5gOwogIH0KCiAgLy8gRGVzdHJ1Y3R1cmUgZmlsbSB0eXBlIGFycmF5cyBmcm9tIHJlc3VsdAoKICBsZXQgZmlsbXNTZWN0aW9uSFRNTCA9ICcnOwogIGlmIChtYXJrZXRfc2NvcGUgPT09ICdpbnRlcm5hdGlvbmFsJyB8fCAhbWFya2V0X3Njb3BlKSB7CiAgICBmaWxtc1NlY3Rpb25IVE1MID0KICAgICAgYnVpbGRGaWxtU2VjdGlvbihpbnRsX3N1cmZhY2UsIGZhbHNlLCAnJiMxMjc3NTc7IFN1cmZhY2UtTGV2ZWwgTWF0Y2hlcycsICdTaW1pbGFyIGluIHByZW1pc2UsIGNoYXJhY3RlciwgYW5kIGdlbmVyYWwgc3RvcnlsaW5lJykgKwogICAgICBidWlsZEZpbG1TZWN0aW9uKGludGxfZGVlcCwgICAgZmFsc2UsICcmIzEyODI2OTsgRGVlcC1MZXZlbCBNYXRjaGVzJywgICAgJ1NpbWlsYXIgaW4gc3BlY2lmaWMgc2NlbmVzLCB0b25lLCBhbmQgdGhlbWF0aWMgbnVhbmNlJyk7CiAgfSBlbHNlIGlmIChtYXJrZXRfc2NvcGUgPT09ICdmaWxpcGlubycpIHsKICAgIGZpbG1zU2VjdGlvbkhUTUwgPQogICAgICBidWlsZEZpbG1TZWN0aW9uKHBoX3N1cmZhY2UsIHRydWUsICcmIzEyNzQ3NzsmIzEyNzQ2OTsgRmlsaXBpbm8gU3VyZmFjZS1MZXZlbCBNYXRjaGVzJywgJ1NpbWlsYXIgaW4gcHJlbWlzZSBhbmQgc3RvcnknKSArCiAgICAgIGJ1aWxkRmlsbVNlY3Rpb24ocGhfZGVlcCwgICAgdHJ1ZSwgJyYjMTI3NDc3OyYjMTI3NDY5OyBGaWxpcGlubyBEZWVwLUxldmVsIE1hdGNoZXMnLCAgICAnU2ltaWxhciBpbiBkZXRhaWwgYW5kIHRoZW1lJykgfHwKICAgICAgJzxkaXYgY2xhc3M9ImJsb2NrLXRpdGxlIHN0YWdnZXItMiIgc3R5bGU9ImNvbG9yOnZhcigtLW11dGVkKSI+Tm8gRmlsaXBpbm8gZmlsbSBtYXRjaGVzIGZvdW5kPC9kaXY+JzsKICB9IGVsc2UgaWYgKG1hcmtldF9zY29wZSA9PT0gJ21peGVkJykgewogICAgZmlsbXNTZWN0aW9uSFRNTCA9CiAgICAgIGJ1aWxkRmlsbVNlY3Rpb24oaW50bF9zdXJmYWNlLCBmYWxzZSwgJyYjMTI3NzU3OyBJbnRlcm5hdGlvbmFsIFN1cmZhY2UtTGV2ZWwgTWF0Y2hlcycsICdTaW1pbGFyIGluIHByZW1pc2UgYW5kIHN0b3J5JykgKwogICAgICBidWlsZEZpbG1TZWN0aW9uKGludGxfZGVlcCwgICAgZmFsc2UsICcmIzEyODI2OTsgSW50ZXJuYXRpb25hbCBEZWVwLUxldmVsIE1hdGNoZXMnLCAgICAnU2ltaWxhciBpbiB0b25lIGFuZCBkZXRhaWwnKSArCiAgICAgIGJ1aWxkRmlsbVNlY3Rpb24ocGhfc3VyZmFjZSwgICB0cnVlLCAgJyYjMTI3NDc3OyYjMTI3NDY5OyBGaWxpcGlubyBTdXJmYWNlLUxldmVsIE1hdGNoZXMnLCAgICAgJ1NpbWlsYXIgaW4gcHJlbWlzZSBhbmQgc3RvcnknKSArCiAgICAgIGJ1aWxkRmlsbVNlY3Rpb24ocGhfZGVlcCwgICAgICB0cnVlLCAgJyYjMTI3NDc3OyYjMTI3NDY5OyBGaWxpcGlubyBEZWVwLUxldmVsIE1hdGNoZXMnLCAgICAgICAgJ1NpbWlsYXIgaW4gdG9uZSBhbmQgZGV0YWlsJyk7CiAgfQoKICBjb25zdCBzdHJlbmd0aHNIVE1MID0gKGFpX2FuYWx5c2lzLnN0cmVuZ3RocyB8fCBbXSkubWFwKHMgPT4KICAgIGA8c3BhbiBjbGFzcz0icGlsbCBzdHJlbmd0aCI+JiMxMDAwMzsgJHtzfTwvc3Bhbj5gKS5qb2luKCcnKTsKICBjb25zdCByaXNrc0hUTUwgPSAoYWlfYW5hbHlzaXMucmlza3MgfHwgW10pLm1hcChyID0+CiAgICBgPHNwYW4gY2xhc3M9InBpbGwgcmlzayI+JiM5ODg4OyAke3J9PC9zcGFuPmApLmpvaW4oJycpOwogIGNvbnN0IHN1Z2dlc3Rpb25zSFRNTCA9IChhaV9hbmFseXNpcy5zdHJhdGVnaWNfc3VnZ2VzdGlvbnMgfHwgW10pLm1hcChzID0+IGAKICAgIDxkaXYgY2xhc3M9InN1Z2dlc3Rpb24taXRlbSI+CiAgICAgIDxkaXYgY2xhc3M9InN1Z2dlc3Rpb24tdGl0bGUiPiR7cy50aXRsZX08L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0ic3VnZ2VzdGlvbi1kZXRhaWwiPiR7cy5kZXRhaWx9PC9kaXY+CiAgICA8L2Rpdj5gKS5qb2luKCcnKTsKICBjb25zdCByb3V0ZXNIVE1MID0gKGFpX2FuYWx5c2lzLmFsdGVybmF0aXZlX3JvdXRlcyB8fCBbXSkubWFwKHIgPT4gYAogICAgPGRpdiBjbGFzcz0icm91dGUtaXRlbSI+CiAgICAgIDxkaXYgY2xhc3M9InJvdXRlLXRpdGxlIj4ke3Iucm91dGV9PC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InJvdXRlLXJhdGlvbmFsZSI+JHtyLnJhdGlvbmFsZX08L2Rpdj4KICAgIDwvZGl2PmApLmpvaW4oJycpOwoKICBjb25zdCBnZW5yZUxhYmVsID0gQXJyYXkuaXNBcnJheShmb3JtRGF0YS5nZW5yZSkgPyBmb3JtRGF0YS5nZW5yZS5qb2luKCcsICcpIDogZm9ybURhdGEuZ2VucmU7CiAgY29uc3QgdG9uZUxhYmVsID0gQXJyYXkuaXNBcnJheShmb3JtRGF0YS50b25lKSA/IGZvcm1EYXRhLnRvbmUuam9pbignLCAnKSA6IGZvcm1EYXRhLnRvbmU7CiAgY29uc3QgYXVkTGFiZWwgPSBBcnJheS5pc0FycmF5KGZvcm1EYXRhLnRhcmdldF9hdWRpZW5jZSkgPyBmb3JtRGF0YS50YXJnZXRfYXVkaWVuY2Uuam9pbignLCAnKSA6IGZvcm1EYXRhLnRhcmdldF9hdWRpZW5jZTsKCiAgcGFuZWwuaW5uZXJIVE1MID0gYAogICAgPCEtLSBGRUFUVVJFIDQ6IEVuaGFuY2VkIHN1Y2Nlc3MgYmxvY2sgd2l0aCBzdWItbWV0cmljcyAtLT4KICAgIDxkaXYgY2xhc3M9InN1Y2Nlc3MtYmxvY2sgc3RhZ2dlci0xIj4KICAgICAgPGRpdiBjbGFzcz0ic3VjY2Vzcy10b3AiPgogICAgICAgIDxkaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWNjZXNzLWxhYmVsIj5QcmVkaWN0ZWQgQ29tbWVyY2lhbCBTdWNjZXNzIFJhdGU8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Y2Nlc3MtdGl0bGUiPiR7Z2VucmVMYWJlbCB8fCAnRmlsbSd9ICZtaWRkb3Q7ICR7dG9uZUxhYmVsIHx8ICcnfSAmbWlkZG90OyAke2F1ZExhYmVsIHx8ICcnfTwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0ibWwtYmFkZ2UiPiR7bWV0aG9kID09PSAneGdib29zdCcgPyAnJiMxMjkzMDI7IFhHQm9vc3QgTUwgUHJlZGljdGlvbicgOiAnJiMxMjgyMDI7IEhldXJpc3RpYyBFc3RpbWF0ZSAmbWRhc2g7IHJ1biB0cmFpbl9tb2RlbC5pcHluYiB0byBlbmFibGUgTUwnfTwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0ibWV0ZXItdHJhY2siPgogICAgICAgICAgICA8ZGl2IGNsYXNzPSJtZXRlci1maWxsICR7cmF0ZUNvbG9yfSIgaWQ9Im1ldGVyLWZpbGwiPjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJtZXRlci1sYWJlbHMiPjxzcGFuPkxvdzwvc3Bhbj48c3Bhbj5NZWRpdW08L3NwYW4+PHNwYW4+SGlnaDwvc3Bhbj48L2Rpdj4KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0icmF0ZS1udW1iZXIiIHN0eWxlPSJjb2xvcjoke3JhdGVDb2xvclZhcn0iPiR7c3VjY2Vzc19yYXRlfTxzcGFuPiU8L3NwYW4+PC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgIDwvZGl2PgogICAgICAke3N1Yl9yZWFzb25zICYmIHN1Yl9yZWFzb25zLmNvbW1lcmNpYWxfc3VjY2VzcyA/IGAKICAgICAgPGRpdiBjbGFzcz0iY29tbWVyY2lhbC1yZWFzb24iPiR7c3ViX3JlYXNvbnMuY29tbWVyY2lhbF9zdWNjZXNzfTwvZGl2PgogICAgICBgIDogJyd9CiAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWNzIj4KICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljJHshc2hvd0ZpbmFuY2lhbCA/ICcgbmEnIDogJyd9Ij4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtbGFiZWwiPiYjMTI4MjAwOyBQcmVkaWN0ZWQgRmluYW5jaWFsIFN1Y2Nlc3M8L2Rpdj4KICAgICAgICAgICR7IXNob3dGaW5hbmNpYWwgPyBgCiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWJhci10cmFjayI+PGRpdiBjbGFzcz0ic3ViLW1ldHJpYy1iYXIiIHN0eWxlPSJ3aWR0aDowJTtiYWNrZ3JvdW5kOnZhcigtLW11dGVkKSI+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXZhbHVlIiBzdHlsZT0iY29sb3I6dmFyKC0tbXV0ZWQpIj5OL0E8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtZGVzYyIgc3R5bGU9ImNvbG9yOnZhcigtLW11dGVkKSI+RmluYW5jaWFsIHN1Y2Nlc3Mgbm90IGEgc3RhdGVkIGdvYWw8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtcmVhc29uIiBzdHlsZT0iY29sb3I6dmFyKC0tbXV0ZWQpIj5UaGlzIGZpbG0gd2FzIG5vdCBkZXNpZ25lZCB3aXRoIHByb2ZpdCBhcyBhIHByaW1hcnkgb2JqZWN0aXZlLjwvZGl2PgogICAgICAgICAgYCA6IHN1Yi5maW5hbmNpYWwuc2NvcmUgPCAwID8gYAogICAgICAgICAgPGRpdiBjbGFzcz0ic3ViLW1ldHJpYy1iYXItdHJhY2siPjxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtYmFyIiBzdHlsZT0id2lkdGg6MCU7YmFja2dyb3VuZDp2YXIoLS1tdXRlZCkiPjwvZGl2PjwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0ic3ViLW1ldHJpYy12YWx1ZSIgc3R5bGU9ImNvbG9yOnZhcigtLW11dGVkKSI+Jm1kYXNoOzwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0ic3ViLW1ldHJpYy1kZXNjIiBzdHlsZT0iY29sb3I6dmFyKC0tbXV0ZWQpIj5CdWRnZXQgbm90IHlldCBkZWNpZGVkPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXJlYXNvbiIgc3R5bGU9ImNvbG9yOnZhcigtLW11dGVkKSI+QSBidWRnZXQgcmFuZ2UgaXMgbmVlZGVkIHRvIGNhbGN1bGF0ZSBmaW5hbmNpYWwgc3VjY2Vzcy4gU2V0IGEgYnVkZ2V0IHRvIHNlZSB0aGlzIG1ldHJpYy48L2Rpdj4KICAgICAgICAgIGAgOiBgCiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWJhci10cmFjayI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtYmFyIiBpZD0iYmFyLWZpbmFuY2lhbCIgc3R5bGU9ImJhY2tncm91bmQ6JHtzY29yZUNvbG9yKHN1Yi5maW5hbmNpYWwuc2NvcmUpfSI+PC9kaXY+CiAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtdmFsdWUiIHN0eWxlPSJjb2xvcjoke3Njb3JlQ29sb3Ioc3ViLmZpbmFuY2lhbC5zY29yZSl9Ij4ke3N1Yi5maW5hbmNpYWwuc2NvcmV9JTwvZGl2PgogICAgICAgICAgPGRpdiBjbGFzcz0ic3ViLW1ldHJpYy1kZXNjIj4ke3N1Yi5maW5hbmNpYWwuZGVzY308L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtcmVhc29uIj4ke3N1Yi5maW5hbmNpYWwucmVhc29ufTwvZGl2PgogICAgICAgICAgYH0KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljIj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtbGFiZWwiPiYjMTI4MTAxOyBQcmVkaWN0ZWQgQXVkaWVuY2UgUmVjZXB0aW9uPC9kaXY+CiAgICAgICAgICAke3N1Yi5hdWRpZW5jZS5zY29yZSA8IDAgPyBgCiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWJhci10cmFjayI+PGRpdiBjbGFzcz0ic3ViLW1ldHJpYy1iYXIiIHN0eWxlPSJ3aWR0aDowJTtiYWNrZ3JvdW5kOnZhcigtLW11dGVkKSI+PC9kaXY+PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXZhbHVlIiBzdHlsZT0iY29sb3I6dmFyKC0tbXV0ZWQpIj4mbWRhc2g7PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWRlc2MiIHN0eWxlPSJjb2xvcjp2YXIoLS1tdXRlZCkiPlRhcmdldCBhdWRpZW5jZSBub3QgeWV0IHNlbGVjdGVkPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXJlYXNvbiIgc3R5bGU9ImNvbG9yOnZhcigtLW11dGVkKSI+U2VsZWN0IGEgdGFyZ2V0IGF1ZGllbmNlIHRvIHNlZSBob3cgd2VsbCB0aGlzIGNvbmNlcHQgYWxpZ25zIHdpdGggdmlld2VyIGV4cGVjdGF0aW9ucy48L2Rpdj4KICAgICAgICAgIGAgOiBgCiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWJhci10cmFjayI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtYmFyIiBpZD0iYmFyLWF1ZGllbmNlIiBzdHlsZT0iYmFja2dyb3VuZDoke3Njb3JlQ29sb3Ioc3ViLmF1ZGllbmNlLnNjb3JlKX0iPjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXZhbHVlIiBzdHlsZT0iY29sb3I6JHtzY29yZUNvbG9yKHN1Yi5hdWRpZW5jZS5zY29yZSl9Ij4ke3N1Yi5hdWRpZW5jZS5zY29yZX0lPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWRlc2MiPiR7c3ViLmF1ZGllbmNlLmRlc2N9PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXJlYXNvbiI+JHtzdWIuYXVkaWVuY2UucmVhc29ufTwvZGl2PgogICAgICAgICAgYH0KICAgICAgICA8L2Rpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljIj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtbGFiZWwiPiYjMTI3NzU3OyBMb25nLXRlcm0gQ3VsdHVyYWwgSW1wYWN0PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWJhci10cmFjayI+CiAgICAgICAgICAgIDxkaXYgY2xhc3M9InN1Yi1tZXRyaWMtYmFyIiBpZD0iYmFyLWN1bHR1cmFsIiBzdHlsZT0iYmFja2dyb3VuZDoke3Njb3JlQ29sb3Ioc3ViLmN1bHR1cmFsLnNjb3JlKX0iPjwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXZhbHVlIiBzdHlsZT0iY29sb3I6JHtzY29yZUNvbG9yKHN1Yi5jdWx0dXJhbC5zY29yZSl9Ij4ke3N1Yi5jdWx0dXJhbC5zY29yZX0lPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLWRlc2MiPiR7c3ViLmN1bHR1cmFsLmRlc2N9PC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzPSJzdWItbWV0cmljLXJlYXNvbiI+JHtzdWIuY3VsdHVyYWwucmVhc29ufTwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgoKICAgICR7ZmlsbXNTZWN0aW9uSFRNTH0KCiAgICA8ZGl2IGNsYXNzPSJibG9jay10aXRsZSBzdGFnZ2VyLTMiPkFJIFN0cmF0ZWdpYyBBbmFseXNpczwvZGl2PgogICAgPGRpdiBjbGFzcz0iYW5hbHlzaXMtYmxvY2sgc3RhZ2dlci0zIj4KICAgICAgPGRpdiBjbGFzcz0iYXNzZXNzbWVudC10ZXh0Ij4ke2FpX2FuYWx5c2lzLm92ZXJhbGxfYXNzZXNzbWVudCB8fCAnJ308L2Rpdj4KICAgICAgJHtzdHJlbmd0aHNIVE1MIHx8IHJpc2tzSFRNTCA/IGAKICAgICAgPGRpdiBjbGFzcz0ic2VjdGlvbi1sYWJlbCIgc3R5bGU9Im1hcmdpbi1ib3R0b206MC44cmVtOyI+U3RyZW5ndGhzICYgUmlza3M8L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0icGlsbHMtcm93Ij4ke3N0cmVuZ3Roc0hUTUx9JHtyaXNrc0hUTUx9PC9kaXY+YCA6ICcnfQogICAgICAke3N1Z2dlc3Rpb25zSFRNTCA/IGAKICAgICAgPGRpdiBjbGFzcz0ic2VjdGlvbi1sYWJlbCIgc3R5bGU9Im1hcmdpbjoxLjJyZW0gMCAwLjhyZW07Ij5TdHJhdGVnaWMgU3VnZ2VzdGlvbnM8L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0ic3VnZ2VzdGlvbnMtbGlzdCI+JHtzdWdnZXN0aW9uc0hUTUx9PC9kaXY+YCA6ICcnfQogICAgICAke3JvdXRlc0hUTUwgPyBgCiAgICAgIDxkaXYgY2xhc3M9InNlY3Rpb24tbGFiZWwiIHN0eWxlPSJtYXJnaW46MS4ycmVtIDAgMC44cmVtOyI+QWx0ZXJuYXRpdmUgUm91dGVzPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InJvdXRlcy1saXN0Ij4ke3JvdXRlc0hUTUx9PC9kaXY+YCA6ICcnfQogICAgICAke2FpX2FuYWx5c2lzLm1hcmtldF9pbnNpZ2h0ID8gYAogICAgICA8ZGl2IGNsYXNzPSJtYXJrZXQtaW5zaWdodCI+JHthaV9hbmFseXNpcy5tYXJrZXRfaW5zaWdodH08L2Rpdj5gIDogJyd9CiAgICA8L2Rpdj4KCiAgICAke3N0b3J5X2FkdmljZSA/IGAKICAgIDxkaXYgY2xhc3M9ImJsb2NrLXRpdGxlIHN0YWdnZXItMyI+JiMxMjgyMTQ7IFN0b3J5IEFkdmlzb3I8L2Rpdj4KICAgIDxkaXYgY2xhc3M9InN0b3J5LWFkdmlzb3ItYmxvY2sgc3RhZ2dlci0zIj4KICAgICAgJHtzdG9yeV9hZHZpY2UudmVyZGljdCA/IGA8ZGl2IGNsYXNzPSJ2ZXJkaWN0Ij4iJHtzdG9yeV9hZHZpY2UudmVyZGljdH0iPC9kaXY+YCA6ICcnfQogICAgICAke3N0b3J5X2FkdmljZS5ob25lc3RfdGFrZSA/IGA8ZGl2IGNsYXNzPSJob25lc3QtdGFrZSI+JHtzdG9yeV9hZHZpY2UuaG9uZXN0X3Rha2V9PC9kaXY+YCA6ICcnfQoKICAgICAgJHtzdG9yeV9hZHZpY2Uud2hhdF93b3JrcyAmJiBzdG9yeV9hZHZpY2Uud2hhdF93b3Jrcy5sZW5ndGggPyBgCiAgICAgIDxkaXYgY2xhc3M9ImFkdmlzb3Itc2VjdGlvbi1sYWJlbCB3b3JrcyI+V2hhdCdzIFdvcmtpbmc8L2Rpdj4KICAgICAgPGRpdiBjbGFzcz0id29ya3MtbGlzdCI+CiAgICAgICAgJHtzdG9yeV9hZHZpY2Uud2hhdF93b3Jrcy5tYXAodyA9PiBgPGRpdiBjbGFzcz0id29ya3MtaXRlbSI+JHt3fTwvZGl2PmApLmpvaW4oJycpfQogICAgICA8L2Rpdj5gIDogJyd9CgogICAgICAke3N0b3J5X2FkdmljZS53aGF0X25lZWRzX3dvcmsgJiYgc3RvcnlfYWR2aWNlLndoYXRfbmVlZHNfd29yay5sZW5ndGggPyBgCiAgICAgIDxkaXYgY2xhc3M9ImFkdmlzb3Itc2VjdGlvbi1sYWJlbCBpc3N1ZXMiPldoYXQgTmVlZHMgV29yazwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJpc3N1ZXMtbGlzdCI+CiAgICAgICAgJHtzdG9yeV9hZHZpY2Uud2hhdF9uZWVkc193b3JrLm1hcCh3ID0+IGA8ZGl2IGNsYXNzPSJpc3N1ZXMtaXRlbSI+JHt3fTwvZGl2PmApLmpvaW4oJycpfQogICAgICA8L2Rpdj5gIDogJyd9CgogICAgICAke3N0b3J5X2FkdmljZS50aGVtYXRpY19mb2N1cyA/IGAKICAgICAgPGRpdiBjbGFzcz0iYWR2aXNvci1zZWN0aW9uLWxhYmVsIj5Db3JlIFRoZW1lIHRvIExlYW4gSW50bzwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJ0aGVtYXRpYy1mb2N1cyI+JHtzdG9yeV9hZHZpY2UudGhlbWF0aWNfZm9jdXN9PC9kaXY+YCA6ICcnfQoKICAgICAgJHtzdG9yeV9hZHZpY2UuY29tcGFyYWJsZV9maWxtcyAmJiBzdG9yeV9hZHZpY2UuY29tcGFyYWJsZV9maWxtcy5sZW5ndGggPyBgCiAgICAgIDxkaXYgY2xhc3M9ImFkdmlzb3Itc2VjdGlvbi1sYWJlbCI+RmlsbXMgaW4gdGhlIFNhbWUgTGFuZTwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJjb21wYXJhYmxlLWZpbG1zIj4KICAgICAgICAke3N0b3J5X2FkdmljZS5jb21wYXJhYmxlX2ZpbG1zLm1hcChmID0+IGA8c3BhbiBjbGFzcz0iY29tcC1maWxtLXBpbGwiPiR7Zn08L3NwYW4+YCkuam9pbignJyl9CiAgICAgIDwvZGl2PmAgOiAnJ30KCiAgICAgICR7c3RvcnlfYWR2aWNlLnN0b3J5X3N1Z2dlc3Rpb25zICYmIHN0b3J5X2FkdmljZS5zdG9yeV9zdWdnZXN0aW9ucy5sZW5ndGggPyBgCiAgICAgIDxkaXYgY2xhc3M9ImFkdmlzb3Itc2VjdGlvbi1sYWJlbCBzdG9yeS1kZXYiPlN0b3J5IERldmVsb3BtZW50IFN1Z2dlc3Rpb25zPC9kaXY+CiAgICAgICR7c3RvcnlfYWR2aWNlLnN0b3J5X3N1Z2dlc3Rpb25zLm1hcChzID0+IGAKICAgICAgICA8ZGl2IGNsYXNzPSJzdG9yeS1zdWdnZXN0aW9uIj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN0b3J5LXN1Z2dlc3Rpb24tdGl0bGUiPiR7cy50aXRsZX08L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3M9InN0b3J5LXN1Z2dlc3Rpb24tZGV0YWlsIj4ke3MuZGV0YWlsfTwvZGl2PgogICAgICAgIDwvZGl2PmApLmpvaW4oJycpfWAgOiAnJ30KICAgIDwvZGl2PmAgOiAnJ30KCiAgICA8ZGl2IGNsYXNzPSJkaXNjbGFpbWVyLWJsb2NrIj4KICAgICAgPGRpdiBjbGFzcz0iZGlzY2xhaW1lci1xdW90ZSI+IkRhdGEgY2FuIG1hcCB0aGUgbGFuZHNjYXBlLCBidXQgb25seSB5b3UgY2FuIGRlY2lkZSB3aGVyZSB0byBnby4iPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9ImRpc2NsYWltZXItdGV4dCI+CiAgICAgICAgRmlsbVZpc2lvbiBpcyBhIGRlY2lzaW9uLXN1cHBvcnQgdG9vbCBwb3dlcmVkIGJ5IG1hY2hpbmUgbGVhcm5pbmcgYW5kIEFJLiBBbGwgcHJlZGljdGlvbnMsIHNjb3JlcywKICAgICAgICBhbmQgc3VnZ2VzdGlvbnMgYXJlIGdlbmVyYXRlZCBmcm9tIHBhdHRlcm5zIGluIGV4aXN0aW5nIGZpbG0gZGF0YSBhbmQgYXJlIGludGVuZGVkIHRvIGhlbHAgeW91CiAgICAgICAgZXhwbG9yZSB5b3VyIG9wdGlvbnMsIG5vdCB0byBkZWZpbmUgdGhlbS4gVGhlIGZpbmFsIGNyZWF0aXZlIHZpc2lvbiwgdGhlIHN0b3J5IHlvdSB3YW50IHRvIHRlbGwsCiAgICAgICAgYW5kIHRoZSByaXNrcyB5b3UncmUgd2lsbGluZyB0byB0YWtlIGFyZSBlbnRpcmVseSB5b3Vycy4gVHJ1c3QgdGhlIGRhdGEgd2hlcmUgaXQgaGVscHMuCiAgICAgICAgVHJ1c3QgeW91ciBpbnN0aW5jdHMgd2hlcmUgaXQgbWF0dGVycyBtb3N0LgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgogIGA7CgogIHNldFRpbWVvdXQoKCkgPT4gewogICAgY29uc3QgZmlsbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdtZXRlci1maWxsJyk7CiAgICBpZiAoZmlsbCkgZmlsbC5zdHlsZS53aWR0aCA9IHN1Y2Nlc3NfcmF0ZSArICclJzsKICAgIGlmIChzaG93RmluYW5jaWFsKSB7CiAgICAgIGNvbnN0IGJmID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Jhci1maW5hbmNpYWwnKTsKICAgICAgaWYgKGJmKSBiZi5zdHlsZS53aWR0aCA9IHN1Yi5maW5hbmNpYWwuc2NvcmUgKyAnJSc7CiAgICB9CiAgICBpZiAoc3ViLmF1ZGllbmNlLnNjb3JlID49IDApIHsKICAgICAgY29uc3QgYmEgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYmFyLWF1ZGllbmNlJyk7CiAgICAgIGlmIChiYSkgYmEuc3R5bGUud2lkdGggPSBzdWIuYXVkaWVuY2Uuc2NvcmUgKyAnJSc7CiAgICB9CiAgICBjb25zdCBiYyA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdiYXItY3VsdHVyYWwnKTsKICAgIGlmIChiYykgYmMuc3R5bGUud2lkdGggPSBzdWIuY3VsdHVyYWwuc2NvcmUgKyAnJSc7CiAgfSwgMTAwKTsKCiAgcGFuZWwuc2Nyb2xsVG9wID0gMDsKfQo=';
    const decoded = atob(encoded);
    const s = document.createElement('script');
    s.textContent = decoded;
    document.head.appendChild(s);

    // Single-select dropdown helpers for Budget Range & Production Schedule
    const s2 = document.createElement('script');
    const encoded2 = 'CiAgICAgIGZ1bmN0aW9uIHRvZ2dsZVNpbmdsZURyb3Bkb3duKGZpZWxkKSB7CiAgICAgICAgdmFyIGRyb3Bkb3duID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Ryb3Bkb3duLScgKyBmaWVsZCk7CiAgICAgICAgdmFyIGRpc3BsYXkgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGlzcGxheS0nICsgZmllbGQpOwogICAgICAgIHZhciBpc09wZW4gPSBkcm9wZG93bi5jbGFzc0xpc3QuY29udGFpbnMoJ29wZW4nKTsKICAgICAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcubXVsdGktc2VsZWN0LWRyb3Bkb3duJykuZm9yRWFjaChmdW5jdGlvbihkKXsgZC5jbGFzc0xpc3QucmVtb3ZlKCdvcGVuJyk7IH0pOwogICAgICAgIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJy5zaW5nbGUtc2VsZWN0LWRpc3BsYXknKS5mb3JFYWNoKGZ1bmN0aW9uKGQpeyBkLmNsYXNzTGlzdC5yZW1vdmUoJ29wZW4nKTsgfSk7CiAgICAgICAgaWYgKCFpc09wZW4pIHsgZHJvcGRvd24uY2xhc3NMaXN0LmFkZCgnb3BlbicpOyBkaXNwbGF5LmNsYXNzTGlzdC5hZGQoJ29wZW4nKTsgfQogICAgICB9CiAgICAgIGZ1bmN0aW9uIHNldFNpbmdsZShmaWVsZCwgdmFsdWUpIHsKICAgICAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZChmaWVsZCkudmFsdWUgPSB2YWx1ZTsKICAgICAgICB2YXIgbGFiZWwgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndmFsLScgKyBmaWVsZCk7CiAgICAgICAgdmFyIHBsYWNlaG9sZGVycyA9IHsgYnVkZ2V0X3JhbmdlOiAnU2VsZWN0IGJ1ZGdldCcsIHByb2R1Y3Rpb25fc2NoZWR1bGU6ICdTZWxlY3Qgc2NoZWR1bGUnIH07CiAgICAgICAgaWYgKHZhbHVlID09PSAnJykgewogICAgICAgICAgbGFiZWwuY2xhc3NOYW1lID0gJ3BsYWNlaG9sZGVyJzsKICAgICAgICAgIGxhYmVsLnRleHRDb250ZW50ID0gcGxhY2Vob2xkZXJzW2ZpZWxkXTsKICAgICAgICB9IGVsc2UgewogICAgICAgICAgbGFiZWwuY2xhc3NOYW1lID0gJyc7CiAgICAgICAgICBsYWJlbC5zdHlsZS5jb2xvciA9ICd2YXIoLS10ZXh0KSc7CiAgICAgICAgICBsYWJlbC50ZXh0Q29udGVudCA9IHZhbHVlOwogICAgICAgIH0KICAgICAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcjZHJvcGRvd24tJyArIGZpZWxkICsgJyAubXVsdGktc2VsZWN0LW9wdGlvbicpLmZvckVhY2goZnVuY3Rpb24ob3B0KSB7CiAgICAgICAgICB2YXIgb3B0VmFsID0gb3B0LmdldEF0dHJpYnV0ZSgnb25jbGljaycpLm1hdGNoKC9zZXRTaW5nbGVcKCdbXiddKycsJyhbXiddKiknXCkvKTsKICAgICAgICAgIHZhciBpc1NlbGVjdGVkID0gb3B0VmFsICYmIG9wdFZhbFsxXSA9PT0gdmFsdWUgJiYgdmFsdWUgIT09ICcnOwogICAgICAgICAgb3B0LmNsYXNzTGlzdC50b2dnbGUoJ3NlbGVjdGVkJywgaXNTZWxlY3RlZCk7CiAgICAgICAgICBvcHQucXVlcnlTZWxlY3RvcignLmNoZWNrJykuaW5uZXJIVE1MID0gaXNTZWxlY3RlZCA/ICcmIzEwMDAzOycgOiAnJzsKICAgICAgICB9KTsKICAgICAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZHJvcGRvd24tJyArIGZpZWxkKS5jbGFzc0xpc3QucmVtb3ZlKCdvcGVuJyk7CiAgICAgICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Rpc3BsYXktJyArIGZpZWxkKS5jbGFzc0xpc3QucmVtb3ZlKCdvcGVuJyk7CiAgICAgIH0KICAgICAgZG9jdW1lbnQuYWRkRXZlbnRMaXN0ZW5lcignbW91c2Vkb3duJywgZnVuY3Rpb24oZSkgewogICAgICAgIGlmICghZS50YXJnZXQuY2xvc2VzdCgnLm11bHRpLXNlbGVjdC13cmFwcGVyJykpIHsKICAgICAgICAgIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJy5tdWx0aS1zZWxlY3QtZHJvcGRvd24nKS5mb3JFYWNoKGZ1bmN0aW9uKGQpeyBkLmNsYXNzTGlzdC5yZW1vdmUoJ29wZW4nKTsgfSk7CiAgICAgICAgICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcuc2luZ2xlLXNlbGVjdC1kaXNwbGF5JykuZm9yRWFjaChmdW5jdGlvbihkKXsgZC5jbGFzc0xpc3QucmVtb3ZlKCdvcGVuJyk7IH0pOwogICAgICAgIH0KICAgICAgfSk7Cg==';
    s2.textContent = atob(encoded2);
    document.head.appendChild(s2);

    // Budget Recommender — renders as a standalone section directly after the success-block.
    const s3 = document.createElement('script');
    s3.textContent = `
(function() {
  function _injectBudgetRecommender(budget_recommendation) {
    if (!budget_recommendation || !budget_recommendation.recommended_range) return;

    // Remove any previously injected block to avoid duplicates on re-run
    var prev = document.getElementById('budget-rec-block');
    if (prev) prev.parentNode.removeChild(prev);

    var successBlock = document.querySelector('.success-block');
    if (!successBlock) return;

    var rec = budget_recommendation;
    var block = document.createElement('div');
    block.id = 'budget-rec-block';
    block.className = 'budget-recommender-block';
    block.innerHTML =
      '<div class="budget-rec-header">' +
        '<span class="budget-rec-title">Budget Recommendation</span>' +
      '</div>' +
      '<div class="budget-rec-body">' +
        '<div class="budget-rec-range-row">' +
          '<span class="budget-recommended-range">' + rec.recommended_range + '</span>' +
          '<span class="budget-rec-range-label">Recommended Range</span>' +
        '</div>' +
        (rec.rationale
          ? '<div class="budget-rec-divider"></div>' +
            '<span class="budget-rec-rationale">' + rec.rationale + '</span>'
          : '') +
        (rec.comparable_film_budgets
          ? '<span class="budget-rec-comparable">&#127916;&nbsp; ' + rec.comparable_film_budgets + '</span>'
          : '') +
        (rec.caveats
          ? '<span class="budget-rec-caveats">&#9888;&nbsp; ' + rec.caveats + '</span>'
          : '') +
      '</div>';

    // Insert as the next sibling of the success-block (full-width separate section)
    successBlock.parentNode.insertBefore(block, successBlock.nextSibling);
  }

  var _origRender = window.renderResults;
  window.renderResults = function(result, formData) {
    _origRender(result, formData);
    var showFinancial = (result.wants_profit !== false && result.wants_profit !== 'false');
    if (showFinancial && result.budget_recommendation) {
      setTimeout(function() {
        _injectBudgetRecommender(result.budget_recommendation);
      }, 150);
    }
  };
})();
`;
    document.head.appendChild(s3);

    // Save Result button — injected into the results panel after analysis completes.
    // Only visible when a logged-in user is detected via window._fvGetCurrentUser().
    const s4 = document.createElement('script');
    s4.textContent = `
(function() {
  var _origRenderSave = window.renderResults;
  window.renderResults = function(result, formData) {
    _origRenderSave(result, formData);
    setTimeout(function() {
      // Remove any previous save button
      var prev = document.getElementById('fv-save-btn-wrap');
      if (prev) prev.parentNode.removeChild(prev);

      var panel = document.getElementById('results');
      if (!panel) return;

      // Build the save button wrapper — inserted after story advisor block
      var wrap = document.createElement('div');
      wrap.id = 'fv-save-btn-wrap';
      wrap.style.cssText = 'display:flex;align-items:center;gap:0;padding:0;background:#13131c;border:1px solid rgba(255,215,0,0.2);border-radius:12px;margin-top:0.5rem;overflow:hidden;';

      // Film reel image - flush left, no margin/padding
      var reel = document.createElement('img');
      reel.src = '/assets/filmreelwheel.png';
      reel.alt = '';
      reel.style.cssText = 'height:auto;width:220px;object-fit:cover;flex-shrink:0;display:block;opacity:0.55;';
      wrap.appendChild(reel);

      // Spacer pushes text+button to the right
      var spacer = document.createElement('div');
      spacer.style.cssText = 'flex:1;';
      wrap.appendChild(spacer);

      // Text label - sits right next to the button
      var label = document.createElement('div');
      label.style.cssText = 'display:flex;flex-direction:row;justify-content:flex-end;align-items:baseline;padding-right:1.5rem;flex-shrink:0;gap:1rem;white-space:nowrap;';

      var headline = document.createElement('span');
      headline.style.cssText = 'font-family:"Inria Serif",serif;font-size:1.35rem;font-style:italic;font-weight:400;color:#f0ece4;line-height:1.25;letter-spacing:-0.01em;';
      headline.textContent = 'Want to save these results?';

      var sub = document.createElement('span');
      sub.id = 'fv-save-sub-label';
      sub.style.cssText = 'font-family:Assistant,sans-serif;font-size:0.82rem;color:#9ca3af;font-style:normal;font-weight:400;';

      function _getIsLoggedIn() {
        var u = typeof window._fvGetCurrentUser === 'function' ? window._fvGetCurrentUser() : null;
        return !!(u && u.id);
      }

      function _updateSubLabel() {
        sub.textContent = _getIsLoggedIn()
          ? "You're in! hit save and it's yours."
          : 'Log in to revisit your analyses anytime.';
      }
      _updateSubLabel();

      label.appendChild(headline);
      label.appendChild(sub);
      wrap.appendChild(label);

      var btn = document.createElement('button');
      btn.id = 'fv-save-btn';
      btn.textContent = 'Save Results';
      btn.style.cssText = [
        'font-family:Assistant,sans-serif',
        'font-size:0.75rem',
        'letter-spacing:0.08em',
        'text-transform:uppercase',
        'font-weight:600',
        'background:#FFD700',
        'border:1px solid #FFD700',
        'color:#0a0a0f',
        'border-radius:6px',
        'padding:0.45rem 1.1rem',
        'cursor:pointer',
        'transition:background 0.2s,color 0.2s,border-color 0.2s',
        'flex-shrink:0',
        'margin-right:1.4rem'
      ].join(';');
      btn.onmouseenter = function() { btn.style.background='#000'; btn.style.color='#FFD700'; btn.style.borderColor='#FFD700'; };
      btn.onmouseleave = function() { btn.style.background='#FFD700'; btn.style.color='#0a0a0f'; btn.style.borderColor='#FFD700'; };

      btn.onclick = function() {
        // Read isLoggedIn live at click time so it reflects post-login state
        var isLoggedIn = _getIsLoggedIn();
        // Guest: open auth modal instead of saving
        if (!isLoggedIn) {
          if (typeof window._fvOpenAuthModal === 'function') window._fvOpenAuthModal();
          return;
        }
        btn.disabled = true;
        btn.textContent = 'Saving\u2026';
        var genres = Array.isArray(formData.genre) ? formData.genre.join(', ') : (formData.genre || '');
        var tones  = Array.isArray(formData.tone)  ? formData.tone.join(', ')  : (formData.tone  || '');
        var pitch  = (formData.story_pitch || '').slice(0, 200);
        var title  = (genres || 'Film') + (tones ? ' \u00b7 ' + tones.split(',')[0].trim() : '');
        // Merge formData fields into the result so they can be fully restored later
        var resultToSave = Object.assign({}, result, {
          story_pitch:         formData.story_pitch         || '',
          main_theme:          formData.main_theme          || '',
          target_audience:     formData.target_audience     || [],
          time_period:         formData.time_period         || [],
          casting_category:    formData.casting_category    || [],
          distribution_goal:   formData.distribution_goal   || [],
          film_purpose:        formData.film_purpose        || [],
          secondary_genre:     formData.secondary_genre     || [],
          budget_range:        formData.budget_range        || '',
          production_schedule: formData.production_schedule || '',
          market_scope:        formData.market_scope        || 'international',
          wants_profit:        (formData.wants_profit !== false),
        });
        fetch((window.FILMVISION_API || '') + '/auth/save_result', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: title, pitch: pitch, genre: genres, tone: tones, result: resultToSave })
        }).then(function(r){ return r.json(); }).then(function(d){
          if (d.ok) {
            btn.textContent = 'Saved!';
            btn.style.background = 'rgba(74,222,128,0.12)';
            btn.style.color = '#4ade80';
            btn.style.borderColor = 'rgba(74,222,128,0.4)';
            btn.onmouseenter = null;
            btn.onmouseleave = null;
            // Notify Vue component to refresh saved list
            window.dispatchEvent(new CustomEvent('fv-result-saved'));
          } else {
            btn.textContent = 'Save failed';
            btn.style.color = '#f87171';
            btn.disabled = false;
          }
        }).catch(function(){
          btn.textContent = 'Save failed';
          btn.style.color = '#f87171';
          btn.disabled = false;
        });
      };
      wrap.appendChild(btn);

      // Insert after the story-advisor-block if it exists, else append to panel
      var storyAdvisor = panel.querySelector('.story-advisor-block');
      if (storyAdvisor && storyAdvisor.parentNode) {
        storyAdvisor.parentNode.insertBefore(wrap, storyAdvisor.nextSibling);
      } else {
        panel.appendChild(wrap);
      }

      // When user logs in after running analysis, update the sub-label so Save works
      window.addEventListener('fv-user-logged-in', function() {
        _updateSubLabel();
      });
    }, 200);
  };
})();
`;
    document.head.appendChild(s4);

    // Global styles for dynamically injected elements (scoped CSS won't reach these)
    if (!document.getElementById('fv-global-styles')) {
      const st = document.createElement('style');
      st.id = 'fv-global-styles';
      st.textContent = [
        'html, body { overflow-x: hidden !important; max-width: 100vw !important; }',
        '.fv-wrap footer { font-family: "Assistant", sans-serif !important; }',
        '.fv-wrap footer .font-title, .fv-wrap footer h4 { font-family: "Inria Serif", serif !important; }',
        '.autocomplete-item { padding:0.5rem 0.9rem !important; font-size:0.82rem !important; font-family:Assistant,sans-serif !important; cursor:pointer !important; display:block !important; text-align:left !important; color:#c8c8d0 !important; line-height:1.4 !important; transition:background 0.15s,color 0.15s !important; }',
        '.autocomplete-item:hover,.autocomplete-item.active { background:rgba(255,255,255,0.05) !important; color:#e7c468 !important; }',
        '.multi-select-option:hover { background:rgba(255,255,255,0.05) !important; color:#e7c468 !important; }',
        '#results { background-color:#f2f2f2 !important; color:#0f0f0f !important; }',
        '.success-block { font-family:Assistant,sans-serif !important; background:#13131c !important; border:1px solid rgba(231,196,104,0.15) !important; border-radius:12px; padding:2rem; margin-bottom:2rem; }',
        '.success-top { display:grid !important; grid-template-columns:1fr auto; gap:1.5rem; align-items:center; margin-bottom:1.8rem; text-align:left !important; }',
        '.success-label { font-family:Assistant,sans-serif !important; font-size:0.7rem; letter-spacing:0.2em; text-transform:uppercase; color:#9ca3af; margin-bottom:0.4rem; text-align:left !important; }',
        '.success-title { font-family:"Inria Serif",serif !important; font-size:1.15rem; margin-bottom:0.4rem; color:#f2f2f2; text-align:left !important; }',
        '.commercial-reason { font-family:Assistant,sans-serif !important; font-size:0.8rem; line-height:1.7; color:#f2f2f2; background:rgba(232,196,106,0.06); border:1px solid rgba(232,196,106,0.2); border-radius:8px; padding:0.9rem 1.1rem; margin-bottom:1.5rem; font-style:italic; text-align:left !important; }',
        '.sub-metrics { display:grid !important; grid-template-columns:repeat(3,1fr) !important; gap:1rem; padding-top:1.5rem; border-top:1px solid rgba(255,255,255,0.06); }',
        '.sub-metric { background:#1a1a26 !important; border-radius:8px; padding:1rem; text-align:left !important; }',
        '.sub-metric-label { font-family:Assistant,sans-serif !important; font-size:0.7rem; letter-spacing:0.15em; text-transform:uppercase; color:#6b6a75; margin-bottom:0.5rem; display:block; text-align:left !important; }',
        '.sub-metric-bar-track { height:5px; background:rgba(255,255,255,0.08); border-radius:99px; overflow:hidden; margin-bottom:0.4rem; display:block; }',
        '.sub-metric-bar { height:100%; border-radius:99px; transition:width 1.8s cubic-bezier(0.16,1,0.3,1); width:0%; display:block; }',
        '.sub-metric-value { font-family:"Inria Serif",serif !important; font-size:1.1rem; font-weight:700; display:block; text-align:left !important; }',
        '.sub-metric-desc { font-family:Assistant,sans-serif !important; font-size:0.7rem; color:#9ca3af; margin-top:0.2rem; line-height:1.5; display:block; text-align:left !important; }',
        '.sub-metric-reason { font-family:Assistant,sans-serif !important; font-size:0.72rem; color:#c8c8d0; line-height:1.55; margin-top:0.5rem; padding-top:0.5rem; border-top:1px solid rgba(255,255,255,0.07); display:block; }',
        '.block-title { font-family:Assistant,sans-serif !important; font-size:0.85rem !important; letter-spacing:0.15em; text-transform:uppercase; color:#0f0f0f !important; margin-bottom:1.4rem; display:flex !important; align-items:center; gap:0.8rem; font-weight:700; }'
        + '.block-title-sub { font-family:Assistant,sans-serif !important; font-size:0.75rem; color:#0f0f0f !important; letter-spacing:0; text-transform:none; font-weight:400; }'
        + '.block-title span { color:#000000 !important; font-size:0.6rem !important; font-weight:400 !important; letter-spacing:0 !important; text-transform:none !important; }',
        '.block-title::after { content:"" !important; flex:1; height:1px; background:rgba(0,0,0,0.25) !important; }',
        '.films-grid { display:grid !important; grid-template-columns:repeat(3,1fr) !important; gap:1rem; margin-bottom:2rem; }',
        '.film-card { background:#13131c !important; border:1px solid rgba(231,196,104,0.12) !important; border-radius:10px; overflow:hidden; transition:border-color 0.2s,transform 0.2s; cursor:pointer; text-decoration:none; display:flex !important; flex-direction:column; color:#f2f2f2 !important; }',
        '.film-card:hover { border-color:rgba(232,196,106,0.35) !important; transform:translateY(-2px); }',
        '.film-poster { width:100%; aspect-ratio:2/3; object-fit:cover; display:block; }',
        '.film-info { padding:0.8rem; display:flex !important; flex-direction:column; flex:1; text-align:left !important; height:100%; }',
        '.film-title { font-family:"Inria Serif",serif !important; font-size:1.1rem; font-weight:700; margin-bottom:0.75rem; line-height:1.3; color:#f2f2f2; display:block; text-align:left !important; }',
        '.film-meta { font-family:Assistant,sans-serif !important; font-size:0.7rem; color:#9ca3af; display:flex !important; justify-content:space-between; align-items:center; margin-bottom:0.85rem; }',
        '.film-score { color:#e8c46a; font-weight:500; }',
        '.film-plot { font-family:Assistant,sans-serif !important; font-size:0.83rem; line-height:1.6; color:rgba(242,242,242,0.6); margin-bottom:1rem; font-style:italic; display:block; text-align:left !important; }',
        '.film-reason-label { font-family:Assistant,sans-serif !important; font-size:0.72rem; font-weight:700; color:#e8c46a; letter-spacing:0.05em; text-transform:uppercase; display:block; margin-bottom:0.3rem; padding-top:0.6rem; border-top:1px solid rgba(255,255,255,0.07); margin-top:0.3rem; text-align:left !important; }',
        '.film-reason { font-family:Assistant,sans-serif !important; font-size:0.73rem; color:#e8c46a; line-height:1.7; margin-bottom:0.8rem; display:block; text-align:left !important; }',
        '.film-link-hint { font-family:Assistant,sans-serif !important; font-size:0.7rem; color:#6b6a75; margin-top:auto !important; padding-top:0.8rem; display:flex !important; align-items:center; gap:0.3rem; }',
        '.analysis-block { background:#13131c !important; border:1px solid rgba(231,196,104,0.12) !important; border-radius:12px; padding:2rem; margin-bottom:1.5rem; text-align:left !important; }',
        '.assessment-text { font-family:"Inria Serif",serif !important; font-size:1rem; line-height:1.7; font-style:italic; color:#f2f2f2; border-left:3px solid #e8c46a; padding-left:1.2rem; margin-bottom:2rem; display:block; text-align:left !important; }',
        '.analysis-section-label { font-family:Assistant,sans-serif !important; font-size:0.75rem; letter-spacing:0.15em; text-transform:uppercase; color:#f2f2f2 !important; font-weight:700; margin:2rem 0 1rem; display:block; text-align:left !important; }',
        '.section-label[style*="margin"] { color:#f2f2f2 !important; text-align:left !important; justify-content:flex-start !important; }',
        '#results .section-label { color:#f2f2f2 !important; text-align:left !important; justify-content:flex-start !important; }',
        '.pills-row { display:flex !important; flex-wrap:wrap; gap:0.5rem; margin-bottom:1.5rem; justify-content:flex-start !important; text-align:left !important; }',
        '.pill { font-family:Assistant,sans-serif !important; font-size:0.68rem; padding:0.3rem 0.75rem; border-radius:99px; letter-spacing:0.05em; }',
        '.pill.strength { background:rgba(74,222,128,0.12); color:#4ade80; border:1px solid rgba(74,222,128,0.3); }',
        '.pill.risk { background:rgba(248,113,113,0.12); color:#f87171; border:1px solid rgba(248,113,113,0.3); }',
        '.suggestions-list { display:flex !important; flex-direction:column; gap:1.5rem; }',
        '.suggestion-item { background:#1a1a26 !important; border-radius:8px; padding:1rem 1.2rem; border-left:3px solid #e8c46a; }',
        '.suggestion-title { font-family:Assistant,sans-serif !important; font-size:0.82rem; font-weight:700; color:#f2f2f2; margin-bottom:0.5rem; display:block; text-align:left !important; }',
        '.suggestion-detail { font-family:Assistant,sans-serif !important; font-size:0.8rem; line-height:1.6; color:#f2f2f2; display:block; text-align:left !important; }',
        '.routes-list { display:flex !important; flex-direction:column; gap:1.5rem; margin-top:1rem; }',
        '.route-item { background:#1a1a26 !important; border-radius:8px; padding:1rem 1.2rem; border-left:3px solid #38bdf8; }',
        '.route-title { font-family:Assistant,sans-serif !important; font-size:0.82rem; font-weight:700; color:#38bdf8; margin-bottom:0.5rem; display:block; text-align:left !important; }',
        '.route-rationale { font-family:Assistant,sans-serif !important; font-size:0.8rem; line-height:1.6; color:#f2f2f2; display:block; text-align:left !important; }',
        '.story-advisor-block { background:#13131c !important; border:1px solid rgba(255,215,0,0.2) !important; border-radius:12px; padding:1.6rem 1.8rem; margin-top:0.5rem; }',
        '.story-advisor-block .verdict { font-family:"Inria Serif",serif !important; font-size:1.1rem; font-weight:700; color:#f2f2f2; font-style:italic; margin-bottom:1.5rem; line-height:1.5; display:block; text-align:left !important; }',
        '.story-advisor-block .honest-take { font-family:Assistant,sans-serif !important; color:#f2f2f2; font-size:0.88rem; line-height:1.7; margin-bottom:1.5rem; display:block; text-align:left !important; }',
        '.story-advisor-block .advisor-section-label { font-family:Assistant,sans-serif !important; font-size:0.75rem; font-weight:700; letter-spacing:0.12em; text-transform:uppercase; color:#e8c46a !important; margin:2rem 0 1rem; display:block; text-align:left !important; }'
        + '.story-advisor-block .advisor-section-label.works { color:#4ade80 !important; }'
        + '.story-advisor-block .advisor-section-label.issues { color:#f87171 !important; }'
        + '.story-advisor-block .advisor-section-label.story-dev { color:#f2f2f2 !important; }',
        '.story-advisor-block .works-list,.story-advisor-block .issues-list { display:flex !important; flex-direction:column; gap:0.6rem; margin-bottom:1.2rem; }',
        '.story-advisor-block .works-item { font-family:Assistant,sans-serif !important; font-size:0.82rem; color:#4ade80; line-height:1.5; padding-left:1rem; position:relative; display:block; text-align:left !important; }',
        '.story-advisor-block .issues-item { font-family:Assistant,sans-serif !important; font-size:0.82rem; color:#f87171; line-height:1.5; padding-left:1rem; position:relative; display:block; text-align:left !important; }',
        '.story-advisor-block .thematic-focus { font-family:Assistant,sans-serif !important; font-size:0.84rem; color:#e8c46a; font-style:italic; line-height:1.6; padding:0.6rem 1rem; border-left:2px solid #e8c46a; margin:0.8rem 0; display:block; text-align:left !important; }',
        '.story-advisor-block .comparable-films { display:flex !important; flex-wrap:wrap; gap:0.4rem; margin:0.5rem 0; justify-content:flex-start !important; text-align:left !important; }',
        '.story-advisor-block .comp-film-pill { background:rgba(232,196,106,0.1); border:1px solid rgba(232,196,106,0.25); border-radius:20px; padding:0.25rem 0.75rem; font-size:0.75rem; color:#e8c46a; font-weight:600; }',
        '.story-advisor-block .story-suggestion { background:#1a1a26 !important; border-radius:8px; padding:1rem 1.5rem; margin-bottom:1.2rem; border-left:3px solid #e8c46a; }',
        '.story-advisor-block .story-suggestion-title { font-family:Assistant,sans-serif !important; font-size:0.78rem; font-weight:700; color:#f2f2f2; margin-bottom:0.5rem; display:block; text-align:left !important; }',
        '.story-advisor-block .story-suggestion-detail { font-family:Assistant,sans-serif !important; font-size:0.8rem; color:#f2f2f2; line-height:1.55; display:block; text-align:left !important; }',
        '.market-insight { font-family:Assistant,sans-serif !important; background:linear-gradient(135deg,rgba(255,215,0,0.08),rgba(255,215,0,0.04)); border:1px solid rgba(255,215,0,0.2); border-radius:10px; padding:1.2rem 1.5rem; margin-top:1.5rem; font-size:0.9rem; font-style:italic; line-height:1.7; color:#f2f2f2; display:block; text-align:left !important; }',
        '.disclaimer-block { margin-top:5rem; padding:3.4rem 1.8rem; border-top:1px solid rgba(0,0,0,0.3); text-align:center; }',
        '.disclaimer-quote { font-family:"Inria Serif",serif !important; font-style:italic; font-size:1.1rem; color:#000000 !important; font-weight:700; margin-bottom:0.8rem; line-height:1.5; display:block;}',
        '.disclaimer-text { font-family:Assistant,sans-serif !important; font-size:0.72rem; color:#888; line-height:1.7; max-width:600px; margin:0 auto; }',
        '.meter-track { height:8px; background:#16161f; border-radius:99px; overflow:hidden; display:block; }',
        '.meter-fill { height:100%; border-radius:99px; transition:width 1.5s cubic-bezier(0.16,1,0.3,1); width:0%; display:block; }',
        '.meter-fill.low { background:#f87171; }',
        '.meter-fill.mid { background:#e8c46a; }',
        '.meter-fill.high { background:#4ade80; }',
        '.meter-labels { display:flex !important; justify-content:space-between; font-size:0.7rem; color:#6b6a75; margin-top:0.4rem; }',
        '.rate-number { font-family:"Inria Serif",serif !important; font-size:4rem; font-weight:900; line-height:1; text-align:left; }',
        '.rate-number span { font-size:1.4rem; font-weight:400; color:#6b6a75; }',
        '.ml-badge { font-family:Assistant,sans-serif !important; font-size:0.7rem; letter-spacing:0.1em; color:#f2f2f2; margin-bottom:0.8rem; opacity:0.8; display:block; text-align:left !important; }',
        '.confirm-modal h3 { color:#FFD700 !important; font-family:Inria Serif,serif !important; font-size:1.1rem !important; font-style:italic !important; }',
        '.confirm-modal { background:#0f0f0f !important; }',
        '.placeholder { color:#9ca3af !important; }',
        'span.placeholder { color:#9ca3af !important; }',
        '.autocomplete-list { max-width:100% !important; overflow-x:hidden !important; }',
        '.autocomplete-item { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; box-sizing:border-box; }',
        '.autocomplete-item span { color:#e7c468 !important; font-weight:700 !important; }',
        /* Budget Recommender — full-width section matching success-block */
        '.budget-recommender-block { background:#13131c !important; border:1px solid rgba(231,196,104,0.15) !important; border-radius:12px; padding:2rem; margin-bottom:2rem; text-align:left !important; }',
        '.budget-recommender-block .budget-rec-header { display:flex !important; align-items:center; gap:0.6rem; margin-bottom:1.5rem; }',
        '.budget-recommender-block .budget-rec-title { font-family:Assistant,sans-serif !important; font-size:0.7rem; font-weight:700; letter-spacing:0.2em; text-transform:uppercase; color:#9ca3af !important; }',
        '.budget-rec-body { display:flex !important; flex-direction:column; gap:1rem; }',
        '.budget-rec-range-row { display:flex !important; align-items:baseline; gap:1rem; flex-wrap:wrap; }',
        '.budget-rec-range-label { font-family:Assistant,sans-serif !important; font-size:0.7rem; letter-spacing:0.12em; text-transform:uppercase; color:#6b6a75; flex-shrink:0; }',
        '.budget-recommended-range { font-family:"Inria Serif",serif !important; font-size:1.6rem; font-weight:700; color:#e8c46a; line-height:1.1; text-align:left !important; }',
        '.budget-rec-divider { height:1px; background:rgba(255,255,255,0.06); width:100%; }',
        '.budget-rec-rationale { font-family:Assistant,sans-serif !important; font-size:0.84rem; line-height:1.7; color:#f2f2f2; display:block; text-align:left !important; }',
        '.budget-rec-comparable { font-family:Assistant,sans-serif !important; font-size:0.78rem; line-height:1.6; color:#9ca3af; padding:0.6rem 0.9rem; background:rgba(255,255,255,0.04); border-radius:6px; display:block; text-align:left !important; font-style:italic; }',
        '.budget-rec-caveats { font-family:Assistant,sans-serif !important; font-size:0.76rem; line-height:1.6; color:#f87171; padding:0.5rem 0.9rem; background:rgba(248,113,113,0.07); border-radius:6px; border-left:2px solid rgba(248,113,113,0.4); display:block; text-align:left !important; }',
        /* Pitch expand modal — Teleport renders outside component scope so must be global */
        '.pitch-modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:99999; display:flex; align-items:center; justify-content:center; backdrop-filter:blur(4px); }',
        '.pitch-modal { width:70%; max-width:900px; min-width:320px; background:#0f0f0f; border:1px solid rgba(231,196,104,0.25); border-radius:14px; padding:1.8rem 2rem 1.6rem; display:flex; flex-direction:column; gap:1rem; }',
        '.pitch-modal-header { display:flex; align-items:center; justify-content:space-between; }',
        '.pitch-modal-title { font-family:Montserrat,sans-serif; font-size:0.7rem; font-weight:400; letter-spacing:0.12em; text-transform:uppercase; color:#6b6a75; }',
        '.pitch-modal-close { background:none; border:none; color:#6b6a75; font-size:0.85rem; cursor:pointer; transition:color 0.2s; padding:0; }',
        '.pitch-modal-close:hover { color:#f87171; }',
        '.pitch-modal-textarea { width:100%; min-height:340px; background:#16161f; border:1px solid rgba(255,255,255,0.07); border-radius:6px; color:#f0ece4; font-family:Assistant,sans-serif; font-size:0.9rem; line-height:1.7; padding:0.9rem 1rem; resize:vertical; outline:none; transition:border-color 0.2s,box-shadow 0.2s; box-sizing:border-box; }',
        '.pitch-modal-textarea:focus { border-color:#FFD700; box-shadow:0 0 0 3px rgba(255,215,0,0.08); }',
        '.pitch-modal-textarea::placeholder { color:#3d3d50; }'
      ].join('\n');
      document.head.appendChild(st);
    }

    // ── Saved results: fetch on mount if logged in, refresh on save ──
    this._fetchSavedList();
    window.addEventListener('fv-result-saved', () => this._fetchSavedList());
    window.addEventListener('fv-user-logged-in', () => this._fetchSavedList());
  },
  beforeUnmount() {
    window.removeEventListener('fv-result-saved', () => this._fetchSavedList());
    window.removeEventListener('fv-user-logged-in', () => this._fetchSavedList());
  },
  methods: {
    async _fetchSavedList() {
      const user = typeof window._fvGetCurrentUser === 'function' ? window._fvGetCurrentUser() : null;
      const API = window.FILMVISION_API || '';
      // If Vue reactive ref hasn't hydrated yet (e.g. on refresh), check session directly
      if (!user) {
        try {
          const meRes = await fetch(`${API}/auth/me`, { credentials: 'include' });
          const meData = await meRes.json();
          if (!meData.user) { this.savedList = []; return; }
          // Session is valid — proceed to fetch saved results
        } catch (_) { this.savedList = []; return; }
      }
      try {
        const res  = await fetch(`${API}/auth/saved_results`, { credentials: 'include' });
        const data = await res.json();
        if (data.results) this.savedList = data.results;
      } catch (_) {}
    },
    async loadSavedResult(id) {
      const API = window.FILMVISION_API || '';
      try {
        const res  = await fetch(`${API}/auth/saved_result/${id}`, { credentials: 'include' });
        const data = await res.json();
        if (data.result && typeof window.renderResults === 'function') {
          // Rebuild formData from saved result — use the full result object for all fields
          const savedResult = data.result;
          const genreArr = data.genre ? data.genre.split(',').map(s => s.trim()).filter(Boolean) : [];
          const toneArr  = data.tone  ? data.tone.split(',').map(s => s.trim()).filter(Boolean)  : [];
          const formData = {
            genre:       genreArr,
            tone:        toneArr,
            story_pitch: savedResult.story_pitch || data.pitch || '',
            main_theme:  savedResult.main_theme || '',
            wants_profit: (savedResult.wants_profit !== false),
            target_audience:   savedResult.target_audience   || [],
            time_period:       savedResult.time_period       || [],
            casting_category:  savedResult.casting_category  || [],
            distribution_goal: savedResult.distribution_goal || [],
            film_purpose:      savedResult.film_purpose      || [],
            secondary_genre:   savedResult.secondary_genre   || [],
            budget_range:      savedResult.budget_range      || '',
            production_schedule: savedResult.production_schedule || '',
            market_scope:      savedResult.market_scope      || 'international',
          };

          // Wait for vanilla-JS globals to be ready (they're injected in Options API mounted,
          // which may run slightly after this composable's mounted on first navigation)
          const _applyFormRestore = () => {
            // Text fields
            const storyEl = document.getElementById('story_pitch');
            if (storyEl) storyEl.value = formData.story_pitch;
            const themeEl = document.getElementById('theme-input-text');
            if (themeEl) themeEl.value = formData.main_theme;

            // Multi-select fields — first clear all, then select saved values
            if (typeof window.toggleOption === 'function') {
              const multiFields = ['genre','tone','target_audience','time_period','casting_category','distribution_goal','film_purpose','secondary_genre'];
              multiFields.forEach(field => {
                const dropdown = document.getElementById('dropdown-' + field);
                if (!dropdown) return;
                // Deselect all currently selected options
                dropdown.querySelectorAll('.multi-select-option.selected').forEach(opt => {
                  const onclickAttr = opt.getAttribute('onclick') || '';
                  const match = onclickAttr.match(/toggleOption\('[^']+',this,'([^']+)'\)/);
                  if (match) window.toggleOption(field, opt, match[1]);
                });
                // Select saved values
                const savedVals = Array.isArray(formData[field]) ? formData[field] : [];
                savedVals.forEach(val => {
                  if (!val) return;
                  dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
                    const onclickAttr = opt.getAttribute('onclick') || '';
                    const match = onclickAttr.match(/toggleOption\('[^']+',this,'([^']+)'\)/);
                    if (match && match[1] === val && !opt.classList.contains('selected')) {
                      window.toggleOption(field, opt, val);
                    }
                  });
                });
              });
            }

            // Single-select fields
            if (typeof window.setSingle === 'function') {
              window.setSingle('budget_range', formData.budget_range);
              window.setSingle('production_schedule', formData.production_schedule);
            }

            // Market scope
            if (typeof window.setScope === 'function') {
              window.setScope(formData.market_scope || 'international');
            }

            // Profit toggle
            if (typeof window.setProfit === 'function') {
              window.setProfit(formData.wants_profit !== false);
            }
          };

          // If globals aren't ready yet (right after navigation), wait up to 500ms
          if (typeof window.toggleOption !== 'function') {
            let waited = 0;
            const interval = setInterval(() => {
              waited += 50;
              if (typeof window.toggleOption === 'function' || waited >= 500) {
                clearInterval(interval);
                _applyFormRestore();
              }
            }, 50);
          } else {
            _applyFormRestore();
          }

          // Render results panel
          window.renderResults(savedResult, formData);
          // Scroll results panel into view
          const panel = document.getElementById('results');
          if (panel) panel.scrollIntoView({ behavior: 'smooth' });
        }
      } catch (_) {}
    },
    async deleteSavedResult(id) {
      const API = window.FILMVISION_API || '';
      try {
        await fetch(`${API}/auth/delete_result/${id}`, { method: 'DELETE', credentials: 'include' });
        this.savedList = this.savedList.filter(r => r.id !== id);
      } catch (_) {}
    },
    syncPitch(event) {
      const val = event.target.value;
      this.pitchModalValue = val;
      const mainTextarea = document.getElementById('story_pitch');
      if (mainTextarea) mainTextarea.value = val;
    },
  },
  watch: {
    pitchModalOpen(val) {
      if (val) {
        // Sync modal value from the main textarea when opening
        const mainTextarea = document.getElementById('story_pitch');
        this.pitchModalValue = mainTextarea ? mainTextarea.value : '';
      }
    },
  },
}
</script>

<style scoped>

  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --surface2: #16161f;
    --border: rgba(255,255,255,0.07);
    --accent: #e8c46a;
    --accent2: #FFD700;
    --accent3: #FFD700;
    --text: #f0ece4;
    --muted: #6b6a75;
    --danger: #f87171;
    --success: #4ade80;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  .fv-wrap {
    background: var(--bg);
    color: var(--text);
    font-family: 'Assistant', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
    width: 100%;
    position: relative;
  }

  .fv-wrap::before {
    content: '';
    position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    z-index: 1000;
    opacity: 0.4;
  }

  header {
    padding: 2.5rem 4rem 2rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: flex-end;
    gap: 2rem;
    position: relative;
  }
  header::after {
    content: '';
    position: absolute;
    bottom: -1px; left: 4rem;
    width: 80px; height: 2px;
    background: var(--accent);
  }
  .logo {
    font-family: 'Inria Serif', serif;
    font-size: 2.4rem;
    font-weight: 900;
    color: var(--accent);
    letter-spacing: -1px;
    line-height: 1;
  }
  .logo span { color: var(--text); font-style: italic; font-weight: 400; }
  .tagline {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: var(--muted);
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding-bottom: 0.3rem;
  }

  main {
    display: grid;
    grid-template-columns: 420px 1fr;
    min-height: calc(100vh - 100px);
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }

  .form-panel {
    border-right: 1px solid var(--border);
    padding: 2.5rem 2rem;
    overflow-y: auto;
    overflow-x: hidden;
    background: #0f0f0f;
    min-width: 0;
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
  }

  .section-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #FFD700 !important;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #e7c468;
  }

  .field-group { margin-bottom: 2rem; }
  .field-group label {
    display: block;
    font-size: 0.75rem;
    font-weight: 400;
    font-family: 'Montserrat', sans-serif;
    color: var(--muted);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 1rem;
  }

  select, input, textarea {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Assistant', sans-serif;
    font-size: 0.85rem;
    padding: 0.7rem 2.2rem 0.7rem 0.9rem;
    transition: border-color 0.2s, box-shadow 0.2s;
    outline: none !important;
    -webkit-appearance: none;
    appearance: none;
    height: 42px;
  }
  select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%236b6a75' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 0.9rem center;
    cursor: pointer;
  }
  input, textarea {
    padding: 0.7rem 0.9rem;
    height: auto;
  }
  select:focus, input:focus, textarea:focus {
    border-color: #FFD700;
    box-shadow: 0 0 0 3px rgba(255,215,0,0.08);
    outline: none !important;
  }
  select:focus-visible, input:focus-visible, textarea:focus-visible {
    outline: none !important;
  }
  textarea { resize: vertical; min-height: 160px; height: 160px; padding-right: 1.2rem; }
  textarea::-webkit-scrollbar { width: 4px; }
  textarea::-webkit-scrollbar-track { background: transparent; }
  textarea::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 99px; }
  textarea::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }
  select option { background: #1a1a24; color: var(--text); }

  /* MULTI-SELECT */
  .multi-select-wrapper {
    position: relative;
  }
  .multi-select-display {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Assistant', sans-serif;
    font-size: 0.85rem;
    padding: 0.6rem 0.9rem;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    text-align: left;
    gap: 0;
    min-height: 42px;
    transition: border-color 0.2s, box-shadow 0.2s;
    user-select: none;
    position: relative;
  }
  .multi-select-display:focus, .multi-select-display.open {
    border-color: #e7c468;
    box-shadow: 0 0 0 3px rgba(255,215,0,0.08);
  }
  .multi-select-display .placeholder {
    color: var(--muted);
    font-size: 0.85rem;
    opacity: 0.7;
  }
  .tag {
    background: rgba(231,196,104,0.1);
    border: 1px solid rgba(231,196,104,0.25);
    color: #e7c468;
    font-family: 'Assistant', sans-serif;
    font-size: 0.8rem;
    padding: 0.3rem 0.6rem;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 0.35rem;
    box-sizing: border-box;
  }
  .tag span:first-child { flex: 1; text-align: left; }
  .tag .remove { flex-shrink: 0; margin-left: auto; opacity: 0.6; font-size: 0.7rem; font-weight: 700; cursor: pointer; padding-left: 0.5rem; }
  .tag .remove:hover { opacity: 1; }


  .multi-select-dropdown {
    display: none;
    position: absolute;
    top: calc(100% + 4px);
    left: 0; right: 0;
    background: #16161f !important; /* Force solid dark background */
    border: 1px solid #e7c468;      /* Force yellow border */
    border-radius: 6px;
    z-index: 9999;                  /* Ensure it's on top */
    max-height: 200px;
    overflow-y: auto;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }
  .multi-select-dropdown.open { display: block; }
  .multi-select-dropdown::-webkit-scrollbar { width: 4px; }
  .multi-select-dropdown::-webkit-scrollbar-track { background: transparent; }
  .multi-select-dropdown::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 99px; }
  .multi-select-dropdown::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }
  .multi-select-option {
    padding: 0.5rem 0.9rem;
    font-size: 0.85rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    transition: background 0.15s;
    text-align: left;
    line-height: 1.4;
  }
  .multi-select-option:hover { background: rgba(255,255,255,0.05); color: #e7c468; }
  .multi-select-option.selected { color: #e7c468; }
  .multi-select-option .check {
    width: 14px;
    height: 14px;
    min-width: 14px;
    border: 1px solid var(--border);
    border-radius: 3px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    flex-shrink: 0;
  }
  .multi-select-option.selected .check {
    background: #e7c468;
    border-color: #e7c468;
    color: #1a1a24;
    font-weight: 700;
    font-size: 0.7rem;
  }
  .multi-select-arrow {
    margin-left: auto;
    font-size: 0.6rem;
    color: var(--muted);
    transition: transform 0.2s;
    flex-shrink: 0;
  }
  .multi-select-display.open .multi-select-arrow { transform: rotate(180deg); }

  /* THEME AUTOCOMPLETE */
  .autocomplete-wrapper { position: relative; width: 100%; overflow: visible; }
  .theme-tag-box {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.5rem 0.9rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
    min-height: 42px;
    cursor: text;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .theme-tag-box:focus-within {
    border-color: #e7c468;
    box-shadow: 0 0 0 3px rgba(255,215,0,0.08);
  }
  #theme-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .autocomplete-list {
    display: none;
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    width: 100%;
    box-sizing: border-box;
    background: #16161f;
    border: 1px solid #e7c468;
    border-radius: 6px;
    z-index: 9999;
    max-height: 200px;
    overflow-y: auto;
    overflow-x: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.6);
  }
  .autocomplete-list.open { display: block; }
  .autocomplete-list::-webkit-scrollbar { width: 4px; }
  .autocomplete-list::-webkit-scrollbar-track { background: transparent; }
  .autocomplete-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 99px; }
  .autocomplete-item {
    padding: 0.5rem 0.9rem;
    font-size: 0.82rem !important;
    font-family: 'Assistant', sans-serif;
    cursor: pointer !important;
    display: block !important;
    text-align: left !important;
    transition: background 0.15s, color 0.15s;
    color: var(--text);
    line-height: 1.4;
  }
  .autocomplete-item:hover, .autocomplete-item.active {
    background: rgba(255,255,255,0.05);
    color: #e7c468;
  }
  .autocomplete-item span { color: #e7c468; font-weight: 700; }

  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; align-items: start; }

  /* Single-select display — identical look to multi-select-display */
  .single-select-display {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Assistant', sans-serif;
    font-size: 0.85rem;
    padding: 0.7rem 0.9rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    height: 42px;
    transition: border-color 0.2s, box-shadow 0.2s;
    user-select: none;
  }
  .single-select-display:focus, .single-select-display.open {
    border-color: #e7c468;
    box-shadow: 0 0 0 3px rgba(255,215,0,0.08);
    outline: none;
  }

  .analyze-btn {
    width: 100%;
    margin-top: 1.8rem;
    padding: 0.75rem 2rem;
    background: #FFD700;
    color: #1e1c21;
    border: 1px solid transparent;
    border-radius: 5px;
    font-family: ui-sans-serif, system-ui, sans-serif;
    font-size: 0.875rem;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background-color 0.3s, color 0.3s, border-color 0.3s;
  }
  .analyze-btn:hover {
    background: #0f0f0f;
    color: #FFD700;
    border-color: #FFD700;
    transform: none;
    box-shadow: none;
  }
  .analyze-btn:active { opacity: 0.85; }
  .analyze-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .analyze-btn .btn-text { display: flex; align-items: center; justify-content: center; gap: 0.5rem; }

  .results-panel {
    padding: 2.5rem 3rem;
    overflow-y: auto;
    overflow-x: hidden;
    /* background: #f2f2f2 url('@/assets/filmbg.jpg') no-repeat right center; */
    background-size: auto 100%;
    color: #0f0f0f;
    min-width: 0;
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
  }

  .empty-state {
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    padding-top: 8rem;
    gap: 1rem;
    color: #888;
    text-align: center;
  }
  .empty-state-card {
    background: #f2f2f2;
    border-radius: 16px;
    padding: 3rem 2.1rem 2.1rem 2.1rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    max-width: 340px;
  }
  .empty-icon { font-size: 3.5rem; opacity: 0.3; }
  .empty-state h3 {
    font-family: 'Inria Serif', serif;
    font-size: 1.5rem;
    color: #888;
    font-style: italic;
  }
  .empty-state p {
    font-family: 'Assistant', sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    max-width: 280px;
    line-height: 1.8;
  }

  /* SUCCESS BLOCK */
  .success-block {
    background: #13131c;
    border: 1px solid rgba(231,196,104,0.15);
    border-radius: 12px;
    padding: 2rem;
    margin-bottom: 2rem;
    animation: fadeUp 0.5s ease both;
  }
  .success-top {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 1.5rem;
    align-items: center;
    margin-bottom: 1.8rem;
  }
  .success-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 0.4rem;
    text-align: left;
  }
  .success-title {
    font-family: 'Inria Serif', serif;
    font-size: 1.1rem;
    margin-bottom: 0.4rem;
    color: #f2f2f2;
    text-align: left;
  }
  .commercial-reason {
    font-size: 0.8rem;
    line-height: 1.7;
    color: #c8c8d0;
    background: rgba(232,196,106,0.06);
    border: 1px solid rgba(232,196,106,0.2);
    border-radius: 8px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 1.5rem;
    font-style: italic;
  }
  .required-star {
    color: var(--danger);
    font-size: 0.7rem;
    vertical-align: super;
    margin-left: 1px;
  }
  .field-error {
    border-color: var(--danger) !important;
    box-shadow: 0 0 0 3px rgba(248,113,113,0.1) !important;
  }
  /* Confirmation modal */
  .confirm-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 9999;
    align-items: center;
    justify-content: center;
  }
  .confirm-overlay.open { display: flex; }
  .confirm-modal {
    background: #0f0f0f !important;
    border: 1px solid rgba(231,196,104,0.4);
    border-radius: 14px;
    padding: 2rem 2.4rem;
    max-width: 420px;
    width: 90%;
    text-align: center;
  }
  .confirm-modal h3 {
    font-family: 'Inria Serif', serif;
    font-size: 1.1rem;
    font-style: italic;
    color: #FFD700 !important;
    margin-bottom: 0.8rem;
  }
  .confirm-modal p {
    font-size: 0.82rem;
    color: var(--muted);
    line-height: 1.6;
    margin-bottom: 0.5rem;
  }
  .confirm-modal .missing-list {
    font-size: 0.8rem;
    color: var(--text);
    margin: 0.8rem 0 1.2rem;
    text-align: left;
    padding-left: 1.4rem;
    list-style: disc;
  }
  .confirm-modal .missing-list li { margin-bottom: 0.4rem; opacity: 0.8; }
  .confirm-btns { display: flex; gap: 0.8rem; justify-content: center; margin-top: 1rem; }
  .confirm-btn-yes {
    background: #FFD700;
    color: #1e1c21;
    border: 1px solid transparent;
    padding: 0.6rem 1.6rem;
    border-radius: 6px;
    font-family: 'Assistant', sans-serif;
    font-weight: 500;
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.3s, color 0.3s, border-color 0.3s;
  }
  .confirm-btn-yes:hover {
    background: #0f0f0f;
    color: #FFD700;
    border-color: #FFD700;
  }
  .confirm-btn-no {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    padding: 0.6rem 1.4rem;
    border-radius: 6px;
    font-family: 'Assistant', sans-serif;
    font-size: 0.82rem;
    cursor: pointer;
    transition: background 0.3s, color 0.3s;
  }
  .confirm-btn-no:hover {
    background: rgba(255,255,255,0.08);
    color: #d1d5db;
  }
  /* Disclaimer */
  .disclaimer-block {
    margin-top: 2rem;
    padding: 1.4rem 1.8rem;
    border-top: 1px solid rgba(231,196,104,0.15);
    text-align: center;
  }
  .disclaimer-quote {
    font-family: 'Inria Serif', serif;
    font-style: italic;
    font-size: 0.95rem;
    color: var(--accent);
    margin-bottom: 0.8rem;
    line-height: 1.5;
  }
  .disclaimer-text {
    font-size: 0.72rem;
    color: #888;
    line-height: 1.7;
    max-width: 600px;
    margin: 0 auto;
    opacity: 0.75;
  }
  .profit-btn {
    padding: 0.45rem 1rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface2);
    color: var(--muted);
    font-family: 'Assistant', sans-serif;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    -webkit-appearance: none;
    appearance: none;
    outline: none;
  }
  .profit-btn:hover { border-color: #FFD700; color: #FFD700; }
  .profit-btn.active { background: rgba(255,215,0,0.12); border-color: #FFD700; color: #FFD700; }
  .sub-metric.na { opacity: 0.4; filter: grayscale(1); }
  .sub-metric.na .sub-metric-label::after { content: " — not applicable"; color: var(--muted); font-size:0.55rem; }
  .scope-btn {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    font-family: 'Assistant', sans-serif;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.5rem 0.9rem;
    cursor: pointer;
    transition: all 0.15s;
    -webkit-appearance: none;
    appearance: none;
    outline: none;
  }
  .scope-btn:hover { border-color: #e7c468; color: #e7c468; }
  .scope-btn.active { background: rgba(255,215,0,0.12); border-color: #FFD700; color: #FFD700; }
  .ph-badge {
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    background: rgba(0,130,80,0.12);
    border: 1px solid rgba(0,180,100,0.25);
    color: #4ade80;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    margin-left: 0.4rem;
    vertical-align: middle;
  }
  .ml-badge {
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.1em;
    color: var(--accent2);
    margin-bottom: 0.8rem;
    opacity: 0.8;
    text-align: left;
  }
  .meter-track {
    height: 8px;
    background: var(--surface2);
    border-radius: 99px;
    overflow: hidden;
  }
  .meter-fill {
    height: 100%;
    border-radius: 99px;
    transition: width 1.5s cubic-bezier(0.16,1,0.3,1);
    width: 0%;
  }
  .meter-fill.low { background: var(--danger); }
  .meter-fill.mid { background: var(--accent); }
  .meter-fill.high { background: var(--success); }
  .meter-labels {
    display: flex;
    justify-content: space-between;
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    color: var(--muted);
    margin-top: 0.4rem;
  }
  .rate-number {
    font-family: 'Inria Serif', serif;
    font-size: 4rem;
    font-weight: 900;
    line-height: 1;
    text-align: left;
  }
  .rate-number span {
    font-size: 1.4rem;
    font-weight: 400;
    color: var(--muted);
  }

  /* SUB-METRICS */
  .sub-metrics {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    padding-top: 1.5rem;
    border-top: 1px solid rgba(255,255,255,0.06);
  }
  .sub-metric {
    background: #1a1a26;
    border-radius: 8px;
    padding: 1rem;
    text-align: left;
  }
  .sub-metric-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 0.5rem;
  }
  .sub-metric-bar-track {
    height: 5px;
    background: rgba(255,255,255,0.08);
    border-radius: 99px;
    overflow: hidden;
    margin-bottom: 0.4rem;
  }
  .sub-metric-bar {
    height: 100%;
    border-radius: 99px;
    transition: width 1.8s cubic-bezier(0.16,1,0.3,1);
    width: 0%;
  }
  .sub-metric-value {
    font-family: 'Inria Serif', serif;
    font-size: 1.1rem;
    font-weight: 700;
    text-align: left;
  }
  .sub-metric-desc {
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: var(--muted);
    margin-top: 0.2rem;
    line-height: 1.5;
    text-align: left;
  }
  .sub-metric-reason {
    font-size: 0.72rem;
    color: #c8c8d0;
    line-height: 1.55;
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid rgba(255,255,255,0.07);
    text-align: left;
  }

  .block-title {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #FFD700 !important;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .block-title::after { content: ''; flex: 1; height: 1px; background: rgba(231,196,104,0.2); }

  .films-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    margin-bottom: 2rem;
  }

  .film-card {
    background: #13131c;
    border: 1px solid rgba(231,196,104,0.12);
    border-radius: 10px;
    overflow: hidden;
    animation: fadeUp 0.5s ease both;
    transition: border-color 0.2s, transform 0.2s;
    cursor: pointer;
    text-decoration: none;
    display: block;
    color: #f2f2f2;
  }
  .film-card:hover { border-color: rgba(232,196,106,0.3); transform: translateY(-2px); }
  .film-poster {
    width: 100%;
    aspect-ratio: 2/3;
    object-fit: cover;
    background: var(--surface2);
  }
  .film-poster-placeholder {
    width: 100%;
    aspect-ratio: 2/3;
    background: var(--surface2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2rem;
    color: var(--muted);
  }
  .film-info { padding: 0.8rem; }
  .film-title {
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.3rem;
    line-height: 1.3;
  }
  .film-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  .film-score { color: var(--accent); font-weight: 500; }
  .film-plot {
    font-size: 0.73rem;
    line-height: 1.5;
    color: #a0a0b0;
    margin-bottom: 0.5rem;
    font-style: italic;
  }
  .film-reason {
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    color: var(--accent2);
    line-height: 1.5;
    border-top: 1px solid rgba(255,255,255,0.07);
    padding-top: 0.5rem;
    margin-top: 0.3rem;
  }
  .film-link-hint {
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: var(--muted);
    margin-top: 0.4rem;
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }

  /* AI ANALYSIS */
  .analysis-block {
    background: #13131c;
    border: 1px solid rgba(231,196,104,0.12);
    border-radius: 12px;
    padding: 2rem;
    margin-bottom: 1.5rem;
    animation: fadeUp 0.6s ease both;
    text-align: left;
  }
  .assessment-text {
    font-family: 'Inria Serif', serif;
    font-size: 1rem;
    line-height: 1.7;
    font-style: italic;
    color: #d8d8e0;
    border-left: 3px solid var(--accent);
    padding-left: 1.2rem;
    margin-bottom: 1.5rem;
  }
  .pills-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.2rem; justify-content: flex-start; text-align: left; }
  .pill {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    padding: 0.3rem 0.75rem;
    border-radius: 99px;
    letter-spacing: 0.05em;
  }
  .pill.strength { background: rgba(74,222,128,0.12); color: #4ade80; border: 1px solid rgba(74,222,128,0.3); }
  .pill.risk { background: rgba(248,113,113,0.12); color: #f87171; border: 1px solid rgba(248,113,113,0.3); }
  .suggestions-list { display: flex; flex-direction: column; gap: 1rem; }
  .suggestion-item {
    background: #1a1a26;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    border-left: 3px solid var(--accent2);
  }
  .suggestion-title { font-size: 0.82rem; font-weight: 700; color: var(--accent2); margin-bottom: 0.3rem; }
  .suggestion-detail { font-size: 0.8rem; line-height: 1.6; color: #c8c8d0; }
  .routes-list { display: flex; flex-direction: column; gap: 0.8rem; margin-top: 1rem; }
  .route-item {
    background: #1a1a26;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    border-left: 3px solid var(--accent3);
  }
  .route-title { font-size: 0.82rem; font-weight: 700; color: var(--accent3); margin-bottom: 0.3rem; }
  .route-rationale { font-size: 0.8rem; line-height: 1.6; color: #c8c8d0; }
  .story-advisor-block {
    background: linear-gradient(135deg, rgba(255,215,0,0.06) 0%, rgba(255,215,0,0.02) 100%);
    border: 1px solid rgba(255,215,0,0.3);
    border-radius: 12px;
    padding: 1.6rem 1.8rem;
    margin-top: 0.5rem;
  }
  .story-advisor-block .verdict {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--accent2);
    font-family: 'Inria Serif', serif;
    font-style: italic;
    margin-bottom: 1.2rem;
    line-height: 1.4;
  }
  .story-advisor-block .honest-take {
    color: #c8c8d0;
    font-size: 0.88rem;
    line-height: 1.7;
    margin-bottom: 1.2rem;
    opacity: 0.9;
  }
  .story-advisor-block .advisor-section-label {
      font-size: 0.6rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #FFD700 !important; /* Hardcoded Yellow with override */
      margin: 1rem 0 0.5rem;
      opacity: 1; /* Increased opacity so it's not faded */
  }
  .story-advisor-block .works-list,
  .story-advisor-block .issues-list {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin-bottom: 0.5rem;
  }
  .story-advisor-block .works-item {
    font-size: 0.82rem;
    color: var(--success);
    line-height: 1.5;
    padding-left: 1rem;
    position: relative;
  }
  .story-advisor-block .works-item::before { content: "✓"; position:absolute; left:0; }
  .story-advisor-block .issues-item {
    font-size: 0.82rem;
    color: var(--danger);
    line-height: 1.5;
    padding-left: 1rem;
    position: relative;
    opacity: 0.85;
  }
  .story-advisor-block .issues-item::before { content: "⚠"; position:absolute; left:0; }
  .story-advisor-block .thematic-focus {
    font-size: 0.84rem;
    color: var(--accent);
    font-style: italic;
    line-height: 1.6;
    padding: 0.6rem 1rem;
    border-left: 2px solid var(--accent);
    margin: 0.5rem 0;
  }
  .story-advisor-block .comparable-films {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.5rem 0;
    justify-content: flex-start;
  }
  .story-advisor-block .comp-film-pill {
    background: rgba(232,196,106,0.1);
    border: 1px solid rgba(232,196,106,0.25);
    border-radius: 20px;
    padding: 0.25rem 0.75rem;
    font-size: 0.75rem;
    color: var(--accent);
    font-weight: 600;
  }
  .story-advisor-block .story-suggestion {
    background: #1a1a26;
    border-radius: 8px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
    border-left: 3px solid var(--accent2);
  }
  .story-advisor-block .story-suggestion-title {
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--accent2);
    margin-bottom: 0.3rem;
    letter-spacing: 0.03em;
  }
  .story-advisor-block .story-suggestion-detail {
    font-size: 0.8rem;
    color: #c8c8d0;
    line-height: 1.55;
  }
  .market-insight {
    background: linear-gradient(135deg, rgba(255,215,0,0.08), rgba(255,215,0,0.04));
    border: 1px solid rgba(255,215,0,0.2);
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    margin-top: 1.5rem;
    font-family: 'Inria Serif', serif;
    font-size: 0.9rem;
    font-style: italic;
    line-height: 1.7;
    color: #c8c8d0;
  }
  .market-insight::before {
    content: '💡 Market Insight — ';
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    font-style: normal;
    color: var(--accent);
    display: block;
    margin-bottom: 0.5rem;
  }

  /* LOADING */
  .loading-overlay {
    display: none;
    position: fixed; inset: 0;
    background: rgba(10,10,15,0.85);
    z-index: 9000;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 1.5rem;
    backdrop-filter: blur(4px);
  }
  .loading-overlay.active { display: flex; }
  .loading-spinner {
    width: 48px; height: 48px;
    border: 3px solid var(--border);
    border-top-color: #FFD700;
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  .loading-text {
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--muted);
  }

  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .stagger-1 { animation-delay: 0.1s; }
  .stagger-2 { animation-delay: 0.2s; }
  .stagger-3 { animation-delay: 0.3s; }
  .stagger-4 { animation-delay: 0.4s; }

  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; }
    header { padding: 1.5rem 1.5rem 1rem; }
    .form-panel { border-right: none; border-bottom: 1px solid var(--border); }
    .results-panel { padding: 1.5rem; }
    .films-grid { grid-template-columns: repeat(2, 1fr); }
    .sub-metrics { grid-template-columns: 1fr; }
  }

  /* ── SAVED ANALYSES ─────────────────────────────────────────────── */
  .saved-section {
    margin-top: 0.5rem;
  }
  .saved-empty {
    font-family: 'Assistant', sans-serif;
    font-size: 0.72rem;
    color: var(--muted);
    line-height: 1.6;
    padding: 0.8rem 0;
    opacity: 0.7;
  }
  .saved-list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    margin-top: 0.6rem;
  }
  .saved-item {
    display: flex;
    align-items: flex-start;
    background: var(--surface2);
    border: 1px solid #2f323b;
    border-radius: 8px;
    transition: border-color 0.2s;
    overflow: hidden;
  }
  .saved-item:hover { border-color: rgba(231,196,104,0.3); }
  .saved-item-main {
    flex: 1;
    padding: 0.75rem 0.9rem;
    cursor: pointer;
  }
  .saved-item-title {
    font-family: 'Inria Serif', serif;
    font-size: 0.85rem;
    color: #f0ece4;
    margin-bottom: 0.2rem;
    line-height: 1.3;
  }
  .saved-item-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    color: #e8c46a;
    letter-spacing: 0.06em;
    margin-bottom: 0.3rem;
  }
  .saved-item-pitch {
    font-family: 'Assistant', sans-serif;
    font-size: 0.72rem;
    color: var(--muted);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .saved-item-del {
    flex-shrink: 0;
    align-self: stretch;
    background: none;
    border: none;
    border-left: 1px solid rgba(255,255,255,0.05);
    color: var(--muted);
    font-size: 0.65rem;
    padding: 0 0.75rem;
    cursor: pointer;
    transition: color 0.2s, background 0.2s;
  }
  .saved-item-del:hover { color: #f87171; background: rgba(248,113,113,0.08); }

  .saved-guest {
    margin-top: 1.5rem;
  }
  .saved-guest-text {
    font-family: 'Assistant', sans-serif;
    font-size: 0.75rem;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1.6;
  }
  .saved-guest-text a {
    color: #e8c46a;
    text-decoration: underline;
    cursor: pointer;
  }
  .saved-guest-text a:hover { color: #FFD700; }

  /* ── STORY PITCH EXPAND BUTTON ──────────────────────────────────── */
  .pitch-expand-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: 'Assistant', sans-serif;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    background: none;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 4px;
    padding: 0.22rem 0.6rem;
    cursor: pointer;
    transition: color 0.2s, border-color 0.2s;
    margin-bottom: 0.1rem;
  }
  .pitch-expand-btn:hover {
    color: #e8c46a;
    border-color: rgba(232,196,106,0.35);
  }

  /* ── STORY PITCH MODAL ──────────────────────────────────────────── */
  .pitch-modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(4px);
  }
  .pitch-modal {
    width: 70%;
    max-width: 900px;
    min-width: 320px;
    background: #0f0f0f;
    border: 1px solid rgba(231,196,104,0.25);
    border-radius: 14px;
    padding: 1.8rem 2rem 1.6rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .pitch-modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .pitch-modal-title {
    font-family: 'Montserrat', sans-serif;
    font-size: 0.7rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
  }
  .pitch-modal-close {
    background: none;
    border: none;
    color: #6b6a75;
    font-size: 0.85rem;
    cursor: pointer;
    transition: color 0.2s;
    padding: 0;
  }
  .pitch-modal-close:hover { color: #f87171; }
  .pitch-modal-textarea {
    width: 100%;
    min-height: 340px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: 'Assistant', sans-serif;
    font-size: 0.9rem;
    line-height: 1.7;
    padding: 0.9rem 1rem;
    resize: vertical;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
    box-sizing: border-box;
  }
  .pitch-modal-textarea:focus {
    border-color: #FFD700;
    box-shadow: 0 0 0 3px rgba(255,215,0,0.08);
  }
  .pitch-modal-textarea::placeholder { color: #3d3d50; }

</style>
