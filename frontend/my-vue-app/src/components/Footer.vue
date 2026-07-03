<script setup>
import footerLogo from '@/assets/footer.png'
import { inject } from 'vue'

const openLegalModal = inject('openLegalModal', () => {})
</script>

<template>
<footer class="border-t border-[#e7c468] bg-[#000000] text-[#f2f2f2]/70" style="font-size: 15px;">
  <div class="max-w-[1200px] mx-auto py-22 px-4 md:px-1 grid grid-cols-1 md:grid-cols-12 gap-12">

    <!-- Column 1: Logo -->
    <div class="md:col-span-4 pr-10 flex items-center">
      <img 
        :src="footerLogo" 
        alt="Footer Logo" 
        class="w-full h-auto object-contain"
      />
    </div>

    <!-- Column 2: About DLC -->
    <div class="md:col-span-3 flex flex-col gap-2 text-left">
      <h4 class="text-[18px] font-title text-white mb-2">DLC - The Dev Team</h4>
      <p class="text-[15px] font-light" style="font-family:'Assistant',sans-serif;">
        DLC is a thesis team focused on research and development in film analytics, bridging academics with industry applications.
      </p>
    </div>

    <!-- Column 3: Legal & How To Use -->
    <div class="md:col-span-2 flex flex-col gap-2 text-left">
      <h4 class="text-[18px] font-title text-white mb-2">Legal</h4>
      <a href="#" @click.prevent="openLegalModal('terms')" class="text-[15px] font-light hover:text-[#FFD700] transition-colors duration-300" style="font-family:'Assistant',sans-serif;">Terms & Conditions</a>
      <a href="#" @click.prevent="openLegalModal('privacy')" class="text-[15px] font-light hover:text-[#FFD700] transition-colors duration-300" style="font-family:'Assistant',sans-serif;">Privacy Policy</a>
      <a href="#" @click.prevent="openLegalModal('howto')" class="text-[15px] font-light hover:text-[#FFD700] transition-colors duration-300" style="font-family:'Assistant',sans-serif;">How to Use</a>
    </div>

    <!-- Column 4: Address & Contact -->
    <div class="md:col-span-3 flex flex-col gap-2 text-left">
      <h4 class="text-[18px] font-title text-white mb-2">Contact</h4>
      <p class="text-[15px] font-light" style="font-family:'Assistant',sans-serif;">Dasmariñas City, Cavite, Philippines</p>
      <p class="text-[15px] font-light" style="font-family:'Assistant',sans-serif;">filmvision.dlc@gmail.com</p>
    </div>

  </div>

  <!-- Footer bottom text -->
  <div class="text-center border-t border-white-700 text-[#f2f2f2]/50 text-[14px] py-7" style="font-family:'Montserrat',sans-serif;text-transform:uppercase;letter-spacing:0.1em;">
    FilmVision • DLC • 2026
  </div>
</footer>
</template>