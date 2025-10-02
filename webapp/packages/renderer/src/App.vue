<template>
  <div id="app" :class="{ 'window-shrunk': isShrunk }">
    <app-header :is-shrunk="isShrunk" @shrink-click="handleShrinkClick"></app-header>
    <router-view :class="{ 'window-shrunk': isShrunk }"></router-view>
  </div>
</template>

<script lang="ts">
  import {defineComponent} from 'vue';
  import AppHeader from '/@/components/AppHeader.vue'
  const { ipcRenderer } = require('electron');

  export default defineComponent({
    name: 'App',
    components: {
      AppHeader
    },
    data() {
      return {
        isShrunk: false,
      };
    },
    mounted() {
      // Listen for shrink state changes from main process
      ipcRenderer.on('window-shrink-state', (_event: any, isShrunk: boolean) => {
        this.isShrunk = isShrunk;
      });
    },
    beforeUnmount() {
      // Clean up event listener
      ipcRenderer.removeAllListeners('window-shrink-state');
    },
    methods: {
      handleShrinkClick() {
        ipcRenderer.send('window-shrink');
      },
    },
  });
</script>

<style>
  #app {
    width: 100vw;
    height: 100vh;
    overflow: hidden;
  }

  #app.window-shrunk {
    width: 400px;
    height: 51px;
  }

  body {
    margin: 0;
    padding: 0;
  }
</style>
