// Where the theme chosen is kept, in the browser
export const THEME_KEY = "vl-theme";

// Runs in the head before the page is painted, so that a page in the dark is not shown light first
export const themeScript = `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});var d=t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`;
