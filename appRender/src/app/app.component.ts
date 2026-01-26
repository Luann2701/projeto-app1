import { Component } from '@angular/core';

@Component({
  selector: 'app-root',
  standalone: true,
  template: `
    <iframe
      src="https://arenacorpoativo.onrender.com"
      style="width:100%; height:100vh; border:none;"
    ></iframe>
  `,
})
export class AppComponent {}
