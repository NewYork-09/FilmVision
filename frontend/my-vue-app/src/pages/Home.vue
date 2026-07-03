<script setup>
import herovid from '@/assets/herovid.mp4'
import filmreel from '@/assets/filmreel.png'
import filmreel2 from '@/assets/filmreel2.png'
import filmslate from '@/assets/filmslate.png'
import filmreelwheel from '@/assets/filmreelwheel.png'
import img1 from '@/assets/image1.png'
import img2 from '@/assets/image2.png'
import img3 from '@/assets/image3.png'
import Footer from '@/components/Footer.vue'

const scrollToContent = () => {
  const content = document.getElementById('description-section')
  content?.scrollIntoView({ behavior: 'smooth' })
}

const functionalities = [
  {
    title: 'Predictive Success Metrics',
    subtitle: 'Predicts the success percentage of your film in terms of commercial, financial, audience perception, and cultural impact.',
    description: 'Uses eXtreme Gradient Boosting (XGBoost) trained on historical box office data, audience ratings, production budgets, and genre distributions to estimate probability of success prior to production.',
    image: img1
  },
  {
    title: 'Similar Films Comparative Analysis',
    subtitle: 'Finds films that are most similar to your idea and provides an AI-assisted explanation on its connection.',
    description: 'Implements K-Nearest Neighbors (KNN) using feature vectors derived from TMDB datasets including genre embeddings, plot metadata, cast overlap, and production patterns to retrieve historically similar films.',
    image: img2
  },
  {
    title: 'AI-Assisted Strategic Recommendations',
    subtitle: 'Suggests how to improve your film idea based on the results found in the Success Metrics and Comparative Analysis.',
    description: 'Applies an ensemble of machine learning to evaluate weaknesses, risk factors, and market alignment, generating strategic recommendations based on historical performance clusters and trend analysis.',
    image: img3
  }
]

const beneficiaries = [
  { 
    role: 'Producers', 
    benefit: 'Assess financial viability, audience demand, and market fit early to reduce production risk. Helps prioritize high-potential projects.' 
  },
  { 
    role: 'Directors', 
    benefit: 'Align creative vision with audience trends and data-backed narrative insights. Supports smarter storytelling decisions.' 
  },
  { 
    role: 'Students', 
    benefit: 'Understand how film elements influence success using real-world data and analytics. Builds practical industry awareness.' 
  },
  { 
    role: 'Companies', 
    benefit: 'Quickly evaluate and compare film proposals using structured, data-driven insights. Improves decision-making efficiency.' 
  }
]

import { onMounted } from 'vue'

onMounted(() => {
  const el = document.querySelector('h1.group span.inline-block')
  if (!el) return

  el.addEventListener('mousemove', (e) => {
    const rect = el.getBoundingClientRect()

    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    el.style.setProperty('--x', `${x}px`)
    el.style.setProperty('--y', `${y}px`)
  })

  el.addEventListener('mouseleave', () => {
    el.style.setProperty('--x', `50%`)
    el.style.setProperty('--y', `50%`)
  })
})
</script>

<template>
  <div class="w-full min-h-screen bg-[#0f0f0f] text-[#f2f2f2] font-body">
    
    <!-- HERO -->
    <section class="relative h-[700px] flex items-center justify-center border-b-[40px] border-[#0f0f0f]">
      <video autoplay muted loop playsinline class="absolute w-full h-full object-cover">
        <source :src="herovid" type="video/mp4" />
      </video>

      <div class="absolute inset-0 bg-black/10"></div>

      <button 
        @click="scrollToContent"
        class="absolute bottom-8 left-1/2 -translate-x-1/2 text-white animate-bounce"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M7 13l5 5 5-5M7 6l5 5 5-5"/>
        </svg>
      </button>
    </section>

    <!-- FILM REEL + QUOTE -->
    <section class="pt-25 pb-20 text-center">

      <!-- FULL WIDTH IMAGE -->
      <!-- <div class="w-full mb-10">
        <img 
          :src="filmreel" 
          class="w-full h-auto block opacity-90"
          alt="Film Reel"
        />
      </div> -->

      <!-- TEXT CONTENT -->
      <div class="px-6 md:px-16 pt-15 pb-30 max-w-[900px] mx-auto flex flex-col items-center gap-6">

        <!-- Quote -->
        <p class="text-[#f2f2f2] text-sm md:text-base font-light leading-relaxed max-w-[700px]">
          "In films, painting and literature, theatre and music come together.<br />
          <span class="text-[#FFD700]">
            But a film is still a 
            <span class="text-lg md:text-xl">film</span>.
          </span>"
        </p>

        <!-- Author -->
        <p class="text-xs uppercase tracking-widest text-[#f2f2f2]/60">
          – Akira Kurosawa
        </p>
      </div>
    </section>

    <!-- DESCRIPTION -->
    <section 
      id="description-section" 
      class="px-0 overflow-visible bg-[#f2f2f2] relative"
    >
      <div class="w-full grid md:grid-cols-12">

        <!-- LEFT COLUMN (FilmVision + Content stacked) -->
        <div class="md:col-span-8 pl-6 md:pl-12 py-20 mt-15 mb-25 flex flex-col gap-6 text-left items-start">
          
          <h1 
            class="font-hero uppercase !text-7xl md:text-9xl lg:text-[180px] leading-none relative group cursor-default select-none !mb-15 md:mb-10"
            style="letter-spacing: 0.43em;"
          >
            <!-- WRAPPER -->
            <span class="relative inline-block">

              <!-- BASE TEXT -->
              <span class="relative z-10 text-[#0f0f0f]">
                FilmVision
              </span>

              <!-- AUTO SHINE LAYER -->
              <span class="shine absolute inset-0 z-10 pointer-events-none">
                FilmVision
              </span>

              <!-- CURSOR HOVER LAYER -->
              <span 
                class="absolute inset-0 z-20 text-[#FFD700] opacity-0 group-hover:opacity-100 pointer-events-none"
                style="
                  letter-spacing: inherit;
                  font: inherit;
                  line-height: inherit;

                  -webkit-mask-image: radial-gradient(circle 80px at var(--x, 50%) var(--y, 50%), black 25%, transparent 65%);
                  mask-image: radial-gradient(circle 80px at var(--x, 50%) var(--y, 50%), black 25%, transparent 65%);
                "
              >
                FilmVision
              </span>

            </span>
          </h1>

          <h2 class="!text-3xl md:text-4xl font-medium font-title tracking-wide !text-[#0f0f0f]">
            Bridging the "Cold-Start" Dilemma
          </h2>

          <p class="text-base md:text-lg lg:text-xl text-[#0f0f0f]/80 leading-relaxed font-light font-body max-w-[700px]">
            FilmVision is an AI-based predictive tool designed to enhance decision-making during the pre-production phase. 
            By analyzing story pitches, genres, and budget ranges against historical market data, 
            we provide creators with a data-driven roadmap to maximize their film's potential.
          </p>

        </div>

        <!-- RIGHT COLUMN (FilmReelWheel full height + overlap) -->
        <div class="md:col-span-4 mt-15 mb-25 relative flex items-end">
          <img 
            :src="filmreelwheel" 
            alt="Film Reel Wheel"
            class="w-[75%] h-auto object-contain ml-auto"
          />
        </div>

      </div>

      <!-- FILMREEL2 (no bottom spacing + underlap) -->
      <div class="w-full relative -mt-[200px]">
        <img 
          :src="filmreel2" 
          class="w-full h-auto block"
          alt="Film Reel"
        />
      </div>
    </section>

    <!-- FUNCTIONALITIES -->
    <section class="py-20 px-6 md:px-16">
      <div class="max-w-[1100px] mx-auto">

        <!-- SECTION HEADER -->
        <div class="mb-12 text-left">
          <h2 class="!text-3xl md:text-4xl font-medium font-title tracking-wide text-[#FFD700] mb-4">
            What Does it Do?
          </h2><br />
          <p class="text-[#f2f2f2]/70 text-sm md:text-base font-light font-body leading-relaxed">
            FilmVision equips creators with data-driven insights before production begins, helping evaluate ideas, reduce uncertainty, and align creative direction with real-world audience and market signals.
          </p>
        </div>

        <!-- CARDS -->
        <div class="flex flex-col gap-10">
          <div 
            v-for="func in functionalities" 
            :key="func.title"
            class="group flex border-t border-b border-[#e7c468] overflow-hidden rounded-md"
          >
            <!-- LEFT: TITLE -->
            <div class="w-[30%] p-6 flex flex-col justify-center bg-[#e7c468] text-left gap-2">

              <!-- TITLE -->
              <h3 class="text-lg md:text-xl font-medium tracking-wide text-[#0f0f0f] font-title text-left mb-4">
                {{ func.title }}
              </h3>

              <!-- SUBTITLE -->
              <p class="text-s md:text-sm text-[#0f0f0f]/70 leading-snug font-light">
                {{ func.subtitle }}
              </p>

            </div>

            <!-- RIGHT: IMAGE + TEXT -->
            <div class="relative w-[70%] h-[280px] overflow-hidden"> <!-- increased height -->

              <!-- Image -->
              <img 
                :src="func.image"
                class="absolute inset-0 w-full h-full object-cover opacity-80"
              />

              <!-- Cover (left → right) -->
              <div class="absolute inset-0 bg-[#0f0f0f] w-0 group-hover:w-full transition-all duration-400 ease-in-out"></div>

              <!-- TEXT -->
              <div class="absolute inset-0 z-10 flex items-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 delay-100">
                <p class="text-[#f2f2f2] text-sm md:text-base leading-relaxed font-light font-body p-6 text-left">
                  {{ func.description }}
                </p>
              </div>
            </div>
          </div>

        </div>
      </div>
    </section>

    <!-- BENEFICIARIES -->
    <section 
      class="relative py-30 px-6 mt-10 md:px-16 bg-cover bg-center bg-fixed"
      :style="{ backgroundImage: `url(${filmslate})` }"
    >
      <!-- Overlay -->
      <div class="absolute inset-0 bg-black/10"></div>

      <div class="relative max-w-[1100px] mx-auto">
        <!-- Title -->
        <h2 class="!text-3xl md:text-4xl font-medium text-center mb-12 font-title tracking-wide text-[#f2f2f2] drop-shadow-[0_6px_24px_rgba(0,0,0,1)]">
          Who Benefits?
        </h2>

        <!-- Cards -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mt-10">
          <div 
            v-for="person in beneficiaries" 
            :key="person.role"
            class="p-8 bg-[#0f0f0f] rounded-md border-t border-b border-[#e7c468] shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
          >
            <!-- Yellow line -->
            <div class="h-1 w-10 bg-[#e7c468] mb-5"></div>

            <!-- TEXT -->
            <h4 class="text-base md:text-lg font-medium uppercase tracking-wide mb-3 font-title text-[#ffffff] text-left">
              {{ person.role }}
            </h4>

            <p class="text-[#f2f2f2] text-sm md:text-base leading-relaxed font-light font-body p-6 text-left">
              {{ person.benefit }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- CALL TO ACTION -->
    <section class="py-16 px-6 md:px-16 text-center">
      <div class="max-w-[900px] mx-auto flex flex-col items-center gap-6">

        <h2 class="!text-3xl md:text-4xl font-medium font-title tracking-wide text-[#FFD700] mb-4">
          Ready to bring your idea to life?
        </h2>

        <p class="text-[#f2f2f2] text-sm md:text-base font-light leading-relaxed mb-6">
          Place your concept in the idea stage and get actionable insights from FilmVision.
        </p>

        <router-link 
          to="/idea" 
          class="bg-[#FFD700] text-[#1e1c21] px-8 py-3 rounded-[5px] font-medium uppercase border border-transparent hover:bg-[#0f0f0f] hover:text-[#FFD700] hover:border-[#FFD700] transition-colors duration-300"
        >
          Go to Idea Stage
        </router-link>

      </div>
    </section>

<!-- FOOTER -->
<Footer />

  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Assistant:wght@300;400;500&family=Inria+Serif:wght@300;400;500&display=swap');

@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@100;200;300&display=swap');

.font-hero {
  font-family: 'Montserrat', sans-serif;
  font-weight: 200; /* thin look */
}

.font-title {
  font-family: 'Inria Serif', serif;
}

.font-body {
  font-family: 'Assistant', sans-serif;
}

.shine {
  background: linear-gradient(
    120deg,
    transparent 0%,
    rgba(255, 215, 0, 0) 30%,
    rgba(255, 215, 0, 1) 50%,
    rgba(255, 215, 0, 0) 70%,
    transparent 100%
  );

  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;

  color: transparent;

  animation: shineMove 5s linear infinite;
  text-shadow: 0 0 18px rgba(255, 215, 0, 0.35);
}

@keyframes shineMove {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>