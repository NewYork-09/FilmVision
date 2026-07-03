import { createRouter, createWebHistory } from 'vue-router'
import Home from '/src/pages/Home.vue'
import IdeaStage from './pages/IdeaStage.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/idea', component: IdeaStage },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})