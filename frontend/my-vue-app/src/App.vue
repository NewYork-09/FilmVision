<template>
  <nav 
    class="nav-container font-body fixed top-0 left-0 w-full z-50"
    :style="{
      transform: showNavbar ? 'translateY(0)' : 'translateY(-100%)',
      transition: 'transform 0.5s cubic-bezier(0.77, 0, 0.175, 1)'
    }"
  >
    <!-- Logo -->
    <div class="logo-wrapper">
      <img src="@/assets/logo.png" alt="Logo" class="logo" />
    </div>

    <!-- Links -->
    <div class="nav-links">
      <router-link 
        to="/" 
        class="nav-link"
      >
        Home
      </router-link>

      <router-link 
        to="/idea" 
        class="nav-link"
      >
        Idea Stage
      </router-link>
    </div>

    <!-- Auth button — pushed to the right -->
    <div class="nav-auth">
      <template v-if="currentUser">
        <span class="nav-username">{{ currentUser.username }}</span>
        <button class="nav-btn nav-btn-logout" @click="handleLogout">Log out</button>
      </template>
      <template v-else>
        <button class="nav-btn nav-btn-login" @click="openModal">Log in</button>
      </template>
    </div>
  </nav>

  <main class="bg-[#0f0f0f] pt-[62px]" style="overflow-x: hidden; width: 100%; max-width: 100%;">
    <router-view />
  </main>

  <!-- ── AUTH MODAL ──────────────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="showModal" class="auth-overlay" @mousedown.self="closeModal">
      <div class="auth-modal">
        <!-- Close -->
        <button class="auth-close" @click="closeModal">&#10005;</button>

        <!-- Tabs -->
        <div class="auth-tabs">
          <button
            class="auth-tab"
            :class="{ active: authMode === 'login' }"
            @click="authMode = 'login'; authError = ''"
          >Log In</button>
          <button
            class="auth-tab"
            :class="{ active: authMode === 'register' }"
            @click="authMode = 'register'; authError = ''"
          >Create Account</button>
        </div>

        <!-- LOGIN FORM -->
        <div v-if="authMode === 'login'" class="auth-form">
          <div class="auth-field">
            <label>Email</label>
            <input v-model="loginEmail" type="email" placeholder="you@example.com" autocomplete="email" />
          </div>
          <div class="auth-field">
            <label>Password</label>
            <input v-model="loginPassword" type="password" placeholder="••••••••" autocomplete="current-password" @keydown.enter="submitLogin" />
          </div>
          <div v-if="authError" class="auth-error">{{ authError }}</div>
          <button class="auth-submit" :disabled="authLoading" @click="submitLogin">
            {{ authLoading ? 'Logging in…' : 'Log In' }}
          </button>
          <p class="auth-switch">
            Don't have an account?
            <span @click="authMode = 'register'; authError = ''">Create one</span>
          </p>
        </div>

        <!-- REGISTER FORM -->
        <div v-else class="auth-form">
          <div class="auth-field">
            <label>Username</label>
            <input v-model="regUsername" type="text" placeholder="filmmaker123" autocomplete="username" />
          </div>
          <div class="auth-field">
            <label>Email</label>
            <input v-model="regEmail" type="email" placeholder="you@example.com" autocomplete="email" />
          </div>
          <div class="auth-field">
            <label>Password <span class="auth-hint">(min. 6 characters)</span></label>
            <input v-model="regPassword" type="password" placeholder="••••••••" autocomplete="new-password" @keydown.enter="submitRegister" />
          </div>
          <div v-if="authError" class="auth-error">{{ authError }}</div>
          <button class="auth-submit" :disabled="authLoading" @click="submitRegister">
            {{ authLoading ? 'Creating account…' : 'Create Account' }}
          </button>
          <p class="auth-switch">
            Already have an account?
            <span @click="authMode = 'login'; authError = ''">Log in</span>
          </p>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- ── LEGAL MODAL ─────────────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="showLegalModal" class="auth-overlay" @mousedown.self="closeLegalModal">
      <div class="legal-modal">
        <!-- Close -->
        <button class="auth-close" @click="closeLegalModal">&#10005;</button>

        <!-- Tabs -->
        <div class="auth-tabs">
          <button class="auth-tab" :class="{ active: legalTab === 'terms' }"   @click="switchLegalTab('terms')">Terms &amp; Conditions</button>
          <button class="auth-tab" :class="{ active: legalTab === 'privacy' }" @click="switchLegalTab('privacy')">Privacy Policy</button>
          <button class="auth-tab" :class="{ active: legalTab === 'howto' }"   @click="switchLegalTab('howto')">How to Use</button>
        </div>

        <!-- SCROLLABLE CONTENT -->
        <div class="legal-body">

          <!-- TERMS & CONDITIONS -->
          <div v-if="legalTab === 'terms'" class="legal-content">
            <h2 class="legal-heading">Terms &amp; Conditions</h2>
            <p class="legal-meta">Effective Date: June 2026 &nbsp;·&nbsp; FilmVision by DLC</p>

            <h3 class="legal-subheading">1. Acceptance of Terms</h3>
            <p>By accessing or using FilmVision, you agree to these Terms &amp; Conditions. If you do not agree, please discontinue use.</p>

            <h3 class="legal-subheading">2. Nature of the Service</h3>
            <p>FilmVision is an academic thesis project developed by DLC. It provides AI-assisted predictive analysis and comparative film insights for informational and educational purposes only. All scores, predictions, and recommendations are estimates generated from historical data patterns and should not be treated as a direct professional financial, legal, or production instruction.</p>

            <h3 class="legal-subheading">3. User Accounts</h3>
            <p>You may register an account to save and revisit your analyses. You are responsible for maintaining the confidentiality of your credentials. DLC reserves the right to suspend accounts that violate these terms.</p>

            <h3 class="legal-subheading">4. Intellectual Property</h3>
            <p>All film data displayed is sourced from TMDB (The Movie Database) under their API terms. AI-generated content is produced via Groq. FilmVision's interface, methodology, and codebase are the intellectual property of the DLC thesis team.</p>

            <h3 class="legal-subheading">5. Limitations of Liability</h3>
            <p>FilmVision is provided "as is." DLC makes no warranties regarding the accuracy of predictions or the commercial outcomes of any film project. DLC shall not be liable for any decisions made based on the application's output.</p>

            <h3 class="legal-subheading">6. Modifications</h3>
            <p>These terms may be updated at any time. Continued use of FilmVision after changes constitutes acceptance of the revised terms.</p>
          </div>

          <!-- PRIVACY POLICY -->
          <div v-if="legalTab === 'privacy'" class="legal-content">
            <h2 class="legal-heading">Privacy Policy</h2>
            <p class="legal-meta">Effective Date: June 2026 &nbsp;·&nbsp; FilmVision by DLC</p>

            <h3 class="legal-subheading">1. Information We Collect</h3>
            <p>When you create an account, we collect your username, email address, and hashed password. When you run an analysis, we store the form inputs and results you choose to save.</p>

            <h3 class="legal-subheading">2. How We Use Your Information</h3>
            <p>Your data is used solely to authenticate your account and to store and retrieve your saved analyses. We do not use your data for marketing, profiling, or any commercial purpose.</p>

            <h3 class="legal-subheading">3. Data Storage</h3>
            <p>Account and analysis data is stored in a local SQLite database managed by the DLC development team. This application is an academic project and is not hosted on commercial cloud infrastructure.</p>

            <h3 class="legal-subheading">4. Third-Party Services</h3>
            <p>FilmVision integrates with TMDB (film data) and Groq (AI inference). Queries made to these services may be subject to their own privacy policies. No personally identifiable information is transmitted to TMDB or Groq.</p>

            <h3 class="legal-subheading">5. Data Retention</h3>
            <p>Saved analyses are retained until you manually delete them. Account data is retained until account deletion is requested.</p>

            <h3 class="legal-subheading">6. Your Rights</h3>
            <p>You may request deletion of your account and associated data at any time by contacting the DLC team at filmvision.dlc@gmail.com.</p>

            <h3 class="legal-subheading">7. Security</h3>
            <p>Passwords are hashed using industry-standard methods. However, as an academic application, FilmVision does not guarantee enterprise-grade security.</p>
          </div>

          <!-- HOW TO USE -->
          <div v-if="legalTab === 'howto'" class="legal-content">
            <h2 class="legal-heading">How to Use FilmVision</h2>
            <p class="legal-meta">A quick guide to getting the most out of your analysis.</p>

            <h3 class="legal-subheading">Step 1 — Fill in Project Details</h3>
            <p>Start with the required fields: <strong>Story Pitch</strong>, <strong>Main Theme</strong>, <strong>Genre</strong>, and <strong>Tone</strong>. These four inputs form the creative fingerprint of your film concept and directly influence all results.</p>
            <p style="margin-top:0.5rem;">Optional fields such as Tonal Hint, Target Audience, and Time Period add precision to the similarity search and predictive scores. It is recommended to fill these up as well to ensure the accuracy and completeness of the results.</p>

            <h3 class="legal-subheading">Step 2 — Set Production Details</h3>
            <p>Select your <strong>Budget Range</strong>, <strong>Production Schedule</strong>, and <strong>Casting Category</strong>. These are used to calculate the Financial Success metric. If Budget Range is left blank, the financial score will show as undecided.</p>

            <h3 class="legal-subheading">Step 3 — Define Your Goals</h3>
            <p>Choose your <strong>Market Scope</strong> (International, Filipino, or Mixed), <strong>Distribution Goal</strong>, <strong>Film Purpose</strong>, and whether you are <strong>aiming for profit</strong>. These settings configure how the analysis is framed and which film datasets are prioritized.</p>

            <h3 class="legal-subheading">Step 4 — Run the Analysis</h3>
            <p>Click <strong>Analyze Film</strong>. The system will retrieve similar films from TMDB, generate AI explanations for each match, compute predictive success metrics, and produce strategic recommendations.</p>
            <p style="margin-top:0.5rem;">Analysis typically takes 15–60 seconds depending on server load.</p>

            <h3 class="legal-subheading">Step 5 — Read the Results</h3>
            <p>Results appear in three sections:</p>
            <p style="margin-top:0.5rem;"><strong>Predictive Metrics</strong> — four scored dimensions: Commercial Success, Financial Success, Audience Reception, and Long-Term Cultural Impact, each with an AI-generated explanation. Below that, there is a Budget Recommendation.</p>
            <p style="margin-top:0.5rem;"><strong>Comparative Analysis</strong> — Surface-Level and Deep-Level film matches with clickable TMDB cards and AI similarity explanations.</p>
            <p style="margin-top:0.5rem;"><strong>AI Insights</strong> — Strategic Analysis (strengths, risks, strategic suggestions, alternative routes) and a Story Advisor (honest creative notes, what works, what needs work, development suggestions).</p>

            <h3 class="legal-subheading">Step 6 — Save Your Results (Optional)</h3>
            <p>Create a free account to save analyses and revisit them anytime from the Saved Analyses panel on the left. Saved results fully restore both the form inputs and the results panel.</p>
          </div>

        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onUnmounted, provide, watch } from 'vue'
import { useRoute } from 'vue-router'

// Scroll to top on every route change
const route = useRoute()
watch(() => route.path, () => { window.scrollTo({ top: 0, left: 0, behavior: 'instant' }) })

// ── Navbar scroll hide ─────────────────────────────────────────────────
const showNavbar = ref(true)
let lastScroll = 0

const handleScroll = () => {
  const currentScroll = window.scrollY
  if (currentScroll > lastScroll && currentScroll > 50) {
    showNavbar.value = false
  } else {
    showNavbar.value = true
  }
  lastScroll = currentScroll
}

onMounted(() => window.addEventListener('scroll', handleScroll))
onUnmounted(() => window.removeEventListener('scroll', handleScroll))

// ── Auth state ─────────────────────────────────────────────────────────
const API = import.meta.env.VITE_API_URL || ''

const currentUser = ref(null)
const showModal   = ref(false)
const authMode    = ref('login')   // 'login' | 'register'
const authError   = ref('')
const authLoading = ref(false)

// Form fields
const loginEmail    = ref('')
const loginPassword = ref('')
const regUsername   = ref('')
const regEmail      = ref('')
const regPassword   = ref('')

// Expose user state to child components via provide/inject
provide('currentUser', currentUser)
provide('openAuthModal', openModal)

// ── Legal modal state ──────────────────────────────────────────────────
const showLegalModal = ref(false)
const legalTab       = ref('terms')  // 'terms' | 'privacy' | 'howto'

function openLegalModal(tab = 'terms') {
  legalTab.value      = tab
  showLegalModal.value = true
}

function closeLegalModal() {
  showLegalModal.value = false
}

function switchLegalTab(tab) {
  legalTab.value = tab
  const body = document.querySelector('.legal-body')
  if (body) body.scrollTop = 0
}

provide('openLegalModal', openLegalModal)

// ── On mount: check if already logged in ──────────────────────────────
onMounted(async () => {
  try {
    const res  = await fetch(`${API}/auth/me`, { credentials: 'include' })
    const data = await res.json()
    if (data.user) currentUser.value = data.user
  } catch (_) {}
})

// ── Modal helpers ──────────────────────────────────────────────────────
function openModal() {
  authMode.value    = 'login'
  authError.value   = ''
  loginEmail.value  = ''
  loginPassword.value = ''
  regUsername.value = ''
  regEmail.value    = ''
  regPassword.value = ''
  showModal.value   = true
}

function closeModal() {
  showModal.value = false
  authError.value = ''
}

// ── Login ──────────────────────────────────────────────────────────────
async function submitLogin() {
  authError.value = ''
  if (!loginEmail.value || !loginPassword.value) {
    authError.value = 'Please fill in all fields.'
    return
  }
  authLoading.value = true
  try {
    const res  = await fetch(`${API}/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: loginEmail.value, password: loginPassword.value })
    })
    const data = await res.json()
    if (!res.ok) { authError.value = data.error || 'Login failed.'; return }
    currentUser.value = data.user
    closeModal()
  } catch (_) {
    authError.value = 'Network error. Please try again.'
  } finally {
    authLoading.value = false
  }
}

// ── Register ───────────────────────────────────────────────────────────
async function submitRegister() {
  authError.value = ''
  if (!regUsername.value || !regEmail.value || !regPassword.value) {
    authError.value = 'Please fill in all fields.'
    return
  }
  authLoading.value = true
  try {
    const res  = await fetch(`${API}/auth/register`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: regUsername.value, email: regEmail.value, password: regPassword.value })
    })
    const data = await res.json()
    if (!res.ok) { authError.value = data.error || 'Registration failed.'; return }
    currentUser.value = data.user
    closeModal()
  } catch (_) {
    authError.value = 'Network error. Please try again.'
  } finally {
    authLoading.value = false
  }
}

// ── Logout ─────────────────────────────────────────────────────────────
async function handleLogout() {
  try {
    await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' })
  } catch (_) {}
  currentUser.value = null
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@100;300;400;500&display=swap');

.font-body {
  font-family: 'Montserrat', sans-serif;
}

/* NAV LAYOUT */
.nav-container {
  display: flex;
  align-items: center;
  gap: 3rem;
  padding: 0.65rem 3rem; 
  background: rgba(15, 15, 15, 0.75);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 4px 6px -4px rgba(0, 0, 0, 0.7);
  border-bottom: 1px solid rgba(255, 255, 255, 0.35);
  transition: transform 0.5s cubic-bezier(0.77, 0, 0.175, 1), box-shadow 0.3s ease;
}

/* LOGO */
.logo-wrapper {
  display: flex;
  align-items: center;
}
.logo {
  height: auto;
  width: 180px;
}

/* LINKS */
.nav-links {
  display: flex;
  gap: 2rem;
}
.nav-link {
  font-weight: 300;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #bcbcbc;
  transition: color 0.2s ease;
}
.nav-link:hover {
  color: #FFD700;
}

/* AUTH SECTION — pushed to far right */
.nav-auth {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.nav-username {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.72rem;
  font-weight: 400;
  letter-spacing: 0.08em;
  color: #e8c46a;
  text-transform: uppercase;
}

.nav-btn {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.7rem;
  font-weight: 400;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  cursor: pointer;
  border-radius: 4px;
  padding: 0.38rem 1rem;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.nav-btn-login {
  background: transparent;
  border: 1px solid rgba(255, 215, 0, 0.5);
  color: #FFD700;
}
.nav-btn-login:hover {
  background: #FFD700;
  color: #0f0f0f;
  border-color: #FFD700;
}
.nav-btn-logout {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #9ca3af;
}
.nav-btn-logout:hover {
  border-color: #f87171;
  color: #f87171;
}

/* ── AUTH MODAL ───────────────────────────────────────────────────── */
.auth-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.auth-modal {
  background: #0f0f0f;
  border: 1px solid rgba(231, 196, 104, 0.25);
  border-radius: 14px;
  padding: 2.4rem 2.6rem 2rem;
  width: 100%;
  max-width: 400px;
  position: relative;
}

.auth-close {
  position: absolute;
  top: 1rem;
  right: 1.2rem;
  background: none;
  border: none;
  color: #6b6a75;
  font-size: 0.85rem;
  cursor: pointer;
  transition: color 0.2s;
}
.auth-close:hover { color: #f87171; }

/* Tabs */
.auth-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 1.8rem;
  border-bottom: 1px solid #2f323b;
}
.auth-tab {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.72rem;
  font-weight: 400;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: none;
  border: none;
  padding: 0.5rem 1.2rem 0.7rem;
  color: #969695;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
  margin-bottom: -1px;
}
.auth-tab.active {
  color: #FFD700;
  border-bottom-color: #FFD700;
}
.auth-tab:hover { color: #e8c46a; }

/* Form */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.auth-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.auth-field label {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.65rem;
  font-weight: 400;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #f5f5f4;
}
.auth-hint {
  font-size: 0.58rem;
  color: #f5f5f4;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 300;
}
.auth-field input {
  background: #0f0f0f;
  border: 1px solid #2f323b;
  border-radius: 6px;
  color: #f0ece4;
  font-family: 'Montserrat', sans-serif;
  font-size: 0.82rem;
  padding: 0.65rem 0.9rem;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.auth-field input:focus {
  border-color: #FFD700;
  box-shadow: 0 0 0 3px rgba(255, 215, 0, 0.08);
}
.auth-field input::placeholder { color: #3d3d50; }

.auth-error {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.7rem;
  color: #f87171;
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: 6px;
  padding: 0.5rem 0.8rem;
}

.auth-submit {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: #FFD700;
  color: #1e1c21;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 0.7rem;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
  margin-top: 0.2rem;
}
.auth-submit:hover {
  background: #0f0f0f;
  color: #FFD700;
  border-color: #FFD700;
}
.auth-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.auth-switch {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.68rem;
  color: #6b6a75;
  text-align: center;
  margin-top: 0.2rem;
}
.auth-switch span {
  color: #e8c46a;
  cursor: pointer;
  text-decoration: underline;
  margin-left: 0.3rem;
}
.auth-switch span:hover { color: #FFD700; }

/* ── LEGAL MODAL ──────────────────────────────────────────────────── */
.legal-modal {
  background: #0f0f0f;
  border: 1px solid rgba(231, 196, 104, 0.25);
  border-radius: 14px;
  padding: 1.5rem 2.6rem 2rem;
  width: 100%;
  max-width: 680px;
  max-height: 90vh;
  position: relative;
  display: flex;
  flex-direction: column;
}

.legal-body {
  overflow-y: auto;
  flex: 1;
  padding-right: 0.4rem;
}
.legal-body::-webkit-scrollbar { width: 4px; }
.legal-body::-webkit-scrollbar-track { background: transparent; }
.legal-body::-webkit-scrollbar-thumb { background: rgba(255,215,0,0.2); border-radius: 99px; }
.legal-body::-webkit-scrollbar-thumb:hover { background: rgba(255,215,0,0.4); }

.legal-content {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding-bottom: 1rem;
}

.legal-heading {
  font-family: 'Montserrat', sans-serif;
  font-size: 1.1rem;
  font-weight: 500;
  color: #FFD700;
  letter-spacing: 0.04em;
  margin-bottom: 0.1rem;
}

.legal-meta {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.62rem;
  color: #6b6a75;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.5rem;
}

.legal-subheading {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #e8c46a;
  margin-top: 0.6rem;
  margin-bottom: 0.1rem;
}

.legal-content p {
  font-family: 'Montserrat', sans-serif;
  font-size: 0.78rem;
  font-weight: 300;
  color: #c8c8d0;
  line-height: 1.75;
}

.legal-content strong {
  color: #f0ece4;
  font-weight: 500;
}
</style>
